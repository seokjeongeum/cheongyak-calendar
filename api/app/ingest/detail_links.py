"""Resolve public complex detail links from provider data, never project tables.

Only the collector performs HTTP. A small persisted metadata record caches each
notice identity; list/detail responses merely validate and project that record.
A search result is a discovery hint, not a link shown to the user: a matching
public detail page must independently confirm its identity first.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

_PROVIDER = "hogangnono"
_ORIGIN = "https://hogangnono.com"
_KIND = "external_detail_link"
_VERSION = "public-identity-v1"
_MAX_BYTES = 1_500_000
_MAX_CANDIDATES = 3
_MAX_CACHE = 256
_APARTMENT_CATEGORIES = {"apt", "unsold", "optional_supply", "public_sale", "private_sale", "private_rental", "public_rental", "apartment", "urban"}
_CACHE: OrderedDict[str, dict] = OrderedDict()


class _StateParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.active = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == "__HGNN_DATA__":
            self.active = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.active = False

    def handle_data(self, data: str) -> None:
        if self.active:
            self.parts.append(data)


def _state(html: str) -> dict:
    parser = _StateParser()
    parser.feed(html)
    try:
        value = json.loads("".join(parser.parts))
        state = value.get("altState", {}) if isinstance(value, dict) else {}
        return state if isinstance(state, dict) else {}
    except (ValueError, TypeError):
        return {}


def _text(raw: Any) -> str:
    return unicodedata.normalize("NFKC", str(raw or "")).strip()


def _name(raw: Any) -> str:
    text = _text(raw).replace("&", "앤")
    # Remove announcement/type descriptions, while retaining phase/block names.
    text = re.sub(r"\((?:\d+회차|조합원\s*취소분|계약취소(?:주택)?|무순위|임의공급|공공지원민간임대|오|오피스텔|아파트)\)", "", text)
    text = re.split(r"(?:일반공급|추가입주자|입주자\s*모집|모집공고|분양공고|잔여세대|선착순)", text, maxsplit=1)[0]
    text = re.sub(r"(?:신혼희망타운\s*\(공공분양\)|오피스텔|아파트)\s*$", "", text)
    return re.sub(r"[^0-9a-z가-힣]", "", text.lower())


def _phase(raw: Any) -> dict[str, tuple[str, ...]]:
    text = _text(raw).lower()
    groups: dict[str, set[str]] = {}
    for match in re.finditer(r"(?<!\d)(\d+)\s*(단지|블록|차)(?!회)|([ivx]+)(?=$|\s|[()])", text):
        if match.group(3):
            groups.setdefault("roman", set()).add(match.group(3))
        else:
            groups.setdefault(match.group(2), set()).add(str(int(match.group(1))))
    return {key: tuple(sorted(values)) for key, values in groups.items()}


def _category(candidate: dict) -> str | None:
    raw = candidate.get("type")
    label = candidate.get("type_name")
    if isinstance(raw, bool):
        return None
    if raw in {0, 1} and label in {"아파트", "오피스텔"} and (raw == 1) != (label == "오피스텔"):
        return None
    if raw == 1 or label == "오피스텔":
        return "officetel"
    if raw == 0 or label == "아파트":
        return "apartment"
    return None


def _same_category(payload: dict, candidate: dict) -> bool:
    kind = _category(candidate)
    category = payload.get("category")
    return kind == "officetel" if category == "officetel" else kind == "apartment" and category in _APARTMENT_CATEGORIES


def _address_identity(raw: Any) -> tuple[tuple[str, ...], str | None]:
    text = _text(raw)
    # Administrative labels can change without the building moving. Matching
    # still requires a local dong/eup/myeon or road and its complete number.
    text = re.sub(r"특례시", "시", text)
    tokens = tuple(re.findall(r"[가-힣A-Za-z0-9]+(?:동|읍|면|리|로|길)", text))
    match = re.search(r"(?:동|읍|면|리|로|길)\s*(\d+(?:-\d+)?)(?=\D|$)", text)
    return tokens, match.group(1) if match else None


def _address_matches(payload: dict, candidate: dict) -> bool:
    left, number = _address_identity(payload.get("address"))
    if not number or not left:
        return False
    for value in (candidate.get("address"), candidate.get("road_address")):
        right, other = _address_identity(value)
        if other == number and right and left[-1] == right[-1]:
            # A same-named road/dong exists in many cities. Require the
            # administrative city/county/district prefix too.
            city = re.findall(r"[가-힣]+(?:시|군|구)", _text(payload.get("address")))
            other_city = re.findall(r"[가-힣]+(?:시|군|구)", _text(value))
            if city and other_city and city[0] == other_city[0] and city[-1] == other_city[-1]:
                return True
    return False


def _official_identity(payload: dict) -> tuple[str, str] | None:
    url = urlparse(str(payload.get("official_url") or ""))
    if url.scheme != "https" or url.hostname not in {"www.applyhome.co.kr", "applyhome.co.kr", "static.applyhome.co.kr"}:
        return None
    query = parse_qs(url.query)
    first = query.get("houseManageNo", [])
    second = query.get("pblancNo", [])
    if len(first) == len(second) == 1 and first[0].isdigit() and second[0].isdigit():
        return first[0], second[0]
    return None


def _candidate_official_identity(candidate: dict) -> tuple[str, str] | None:
    base = candidate.get("baseinfo")
    info = base.get("applyHomeInfo") if isinstance(base, dict) else None
    info = info if isinstance(info, dict) else {}
    first, second = str(info.get("houseManageNo") or ""), str(info.get("pblancNo") or "")
    return (first, second) if first.isdigit() and second.isdigit() else None


def _match_basis(payload: dict, candidate: dict) -> str | None:
    if not _same_category(payload, candidate):
        return None
    left_phase, right_phase = _phase(payload.get("title")), _phase(candidate.get("name"))
    # An explicit different block/phase must never become an alias match.
    if any(key in right_phase and right_phase[key] != values for key, values in left_phase.items()):
        return None
    official = _official_identity(payload)
    if official and official == _candidate_official_identity(candidate):
        return "official_announcement_identity"
    if left_phase != right_phase:
        return None
    if _name(payload.get("title")) == _name(candidate.get("name")) and _address_matches(payload, candidate):
        return "name_category_address"
    return None


def _identity(payload: dict) -> str:
    category = "officetel" if payload.get("category") == "officetel" else "apartment" if payload.get("category") in _APARTMENT_CATEGORIES else _text(payload.get("category"))
    value = [_text(payload.get("title")), category, _text(payload.get("address"))]
    value.append(_official_identity(payload))
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _safe_url(raw: Any) -> bool:
    return bool(isinstance(raw, str) and re.fullmatch(r"https://hogangnono\.com/apt/[A-Za-z0-9]{3,32}", raw))


def public_detail_link(payload: dict, rules: list[dict]) -> str | None:
    """Validate cached evidence without HTTP or database reads."""
    links = set()
    identity = _identity(payload)
    for rule in rules:
        if rule.get("kind") != _KIND or rule.get("provider") != _PROVIDER or rule.get("source") != _PROVIDER:
            continue
        candidate = rule.get("candidate")
        url = rule.get("url")
        if (rule.get("verification") == "external_verified" and rule.get("notice_identity") == identity
                and _safe_url(url) and isinstance(candidate, dict)
                and str(candidate.get("id")) == url.rsplit("/", 1)[-1] and _match_basis(payload, candidate)):
            links.add(url)
    return next(iter(links)) if len(links) == 1 else None


def _cached(payload: dict, rules: list[dict], now: datetime) -> dict | None:
    identity = _identity(payload)
    candidates = [rule for rule in rules if rule.get("kind") == _KIND and rule.get("provider") == _PROVIDER
                  and rule.get("resolver_version") == _VERSION and rule.get("notice_identity") == identity]
    memory = _CACHE.get(identity)
    if memory:
        candidates.append(memory)
    for rule in candidates:
        try:
            until = datetime.fromisoformat(rule["retry_after"])
            if until.tzinfo is not None and now < until:
                if rule.get("url") and public_detail_link(payload, [rule]) is None:
                    continue
                return rule
        except (KeyError, ValueError, TypeError):
            pass
    return None


async def _read(client: httpx.AsyncClient, url: str, *, params: dict | None = None) -> str:
    async with client.stream("GET", url, params=params, timeout=8.0, follow_redirects=False) as response:
        response.raise_for_status()
        if int(response.headers.get("content-length", "0")) > _MAX_BYTES:
            raise ValueError("Provider page exceeds bounded download size")
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > _MAX_BYTES:
                raise ValueError("Provider page exceeds bounded download size")
        return data.decode("utf-8", errors="replace")


def _compact(candidate: dict) -> dict:
    result = {key: _text(candidate.get(key))[:500] for key in ("id", "name", "address", "road_address", "type_name") if candidate.get(key) is not None}
    if candidate.get("type") in {0, 1}:
        result["type"] = candidate["type"]
    base = candidate.get("baseinfo")
    info = base.get("applyHomeInfo") if isinstance(base, dict) else None
    if isinstance(info, dict):
        result["baseinfo"] = {"applyHomeInfo": {key: info.get(key) for key in ("houseManageNo", "pblancNo")}}
    return result


async def _resolve(payload: dict, client: httpx.AsyncClient) -> tuple[dict | None, str]:
    query = re.split(r"(?:일반공급|추가입주자|입주자\s*모집|모집공고|분양공고|잔여세대|선착순)", _text(payload.get("title")), maxsplit=1)[0].strip()[:40]
    state = _state(await _read(client, _ORIGIN + "/search", params={"q": query}))
    store = state.get("SearchStore")
    results = store.get("searchResults") if isinstance(store, dict) else None
    candidates = results.get("apt") if isinstance(results, dict) else None
    rows = candidates.get("list", []) if isinstance(candidates, dict) else None
    if not isinstance(rows, list):
        return None, "search_result_unavailable"
    plausible = []
    for row in rows:
        if not isinstance(row, dict) or not re.fullmatch(r"[A-Za-z0-9]{3,32}", str(row.get("id") or "")) or not _same_category(payload, row):
            continue
        # The detail may expose a current official business identity even if
        # its marketing name changed. Exact parcel/type hints permit that
        # check; neither hint alone can authorize a published link.
        if _name(payload.get("title")) == _name(row.get("name")) or _address_matches(payload, row):
            plausible.append(row)
    if len(plausible) > _MAX_CANDIDATES:
        return None, "ambiguous_search_results"
    confirmed: dict[str, dict] = {}
    for row in plausible:
        state = _state(await _read(client, _ORIGIN + "/apt/" + str(row["id"])))
        store = state.get("AptStore")
        detail = store.get("detail") if isinstance(store, dict) else None
        if isinstance(detail, dict) and str(detail.get("id")) == str(row["id"]) and _match_basis(payload, detail):
            confirmed[str(row["id"])] = _compact(detail)
    if len(confirmed) != 1:
        return None, "ambiguous_identity" if confirmed else "identity_not_confirmed"
    return next(iter(confirmed.values())), "resolved"


async def enrich_detail_link(payload: dict, *, client: httpx.AsyncClient, previous_rules: list[dict] | None = None,
                             now: datetime | None = None) -> dict:
    """Best-effort bounded collector enrichment; failure never blocks a feed."""
    if payload.get("category") not in _APARTMENT_CATEGORIES | {"officetel"}:
        return payload
    now = now or datetime.now(timezone.utc)
    rules = list(payload.get("rules") or [])
    cached = _cached(payload, [*rules, *(previous_rules or [])], now)
    if cached is None:
        candidate, status = None, "provider_unavailable"
        try:
            async with asyncio.timeout(20):
                candidate, status = await _resolve(payload, client)
        except (httpx.HTTPError, ValueError, TypeError, TimeoutError):
            pass
        cached = {"kind": _KIND, "effect": "metadata", "source": _PROVIDER, "provider": _PROVIDER,
                  "resolver_version": _VERSION, "notice_identity": _identity(payload), "status": status,
                  "verification": "external_verified" if candidate else "unknown",
                  "checked_at": now.isoformat(), "retry_after": (now + (timedelta(days=90) if candidate else timedelta(hours=3) if status == "provider_unavailable" else timedelta(days=7))).isoformat()}
        if candidate:
            cached.update(url=_ORIGIN + "/apt/" + candidate["id"], candidate=candidate,
                          match_basis=_match_basis(payload, candidate))
        _CACHE[_identity(payload)] = cached
        _CACHE.move_to_end(_identity(payload))
        while len(_CACHE) > _MAX_CACHE:
            _CACHE.popitem(last=False)
    rules = [rule for rule in rules if not (rule.get("kind") == _KIND and rule.get("provider") == _PROVIDER)]
    return {**payload, "rules": [*rules, cached]}
