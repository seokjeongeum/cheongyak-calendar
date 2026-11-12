"""Checked public sale tables; installments and fees never become rent.

The existing rules JSON holds the row identity and component provenance. Only
explicitly headed rows with reconciled printed amounts are emitted as official
totals. An unsupported table remains unknown rather than borrowing AI semantics.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal

PRICE_PARSER_VERSION = "official-price-tables-2026-11-09-v1"
PRICE_METADATA_KINDS = {"price_details", "additional_costs", "price_extraction"}
UNVERIFIED = {"ai_unverified", "auto_unverified"}
MONEY = r"\d{1,3}(?:,\d{3})+"
ROOMS = r"[1-9]\d{2,4}(?:\s*[,·]\s*[1-9]\d{2,4})*"
AMOUNTS = (r"(?P<total>" + MONEY + r")\s+(?P<first>" + MONEY + r")\s+"
           r"(?:(?P<interim>" + MONEY + r")\s+)?(?P<balance>" + MONEY + r")(?![\d,])")
ROW = re.compile(
    r"(?<![\w.,])(?P<building>[A-Z]|[1-9]\d{1,4})\s+(?P<room>" + ROOMS + r")\s+"
    r"(?P<exclusive>\d{1,3}\.\d{1,6})\s+(?P<common>\d{1,3}\.\d{1,6})"
    r"(?P<areas>[\d.\s]{0,100}?)\s+" + AMOUNTS
)
ROOM_ROW = re.compile(
    r"(?<![\w.,])(?P<room>" + ROOMS + r")\s+"
    r"(?P<exclusive>\d{1,3}\.\d{1,6})\s+(?P<common>\d{1,3}\.\d{1,6})"
    r"(?P<areas>[\d.\s]{0,100}?)\s+" + AMOUNTS
)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _normal(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _evidence(url: str, digest: str, page: dict, quote: str) -> dict:
    return {"verification": "official", "source": "official_document_parser",
            "parser_version": _parser_version(), "price_parser_version": PRICE_PARSER_VERSION,
            "document_hash": digest, "evidence_url": url,
            "evidence_page": page["page"], "evidence_text": quote[:1600]}


def _parser_version() -> str:
    from .official_rules import PARSER_VERSION
    return PARSER_VERSION


def _rule(kind: str, evidence: dict, **fields) -> dict:
    body = {"kind": kind, "effect": "metadata", **evidence, **fields}
    body["id"] = "price-" + hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:18]
    return body


def _site(text: str, offset: int, fallback: str) -> str:
    """A numbered site heading is a name, not a guessed dwelling identity."""
    headings = list(re.finditer(r"(?:^|\n)\s*\d+\)\s*([^\n(]{3,100})(?:\(|\n)", text[:offset]))
    if headings:
        return headings[-1][1].strip()
    return fallback


def _supply_area(match: re.Match) -> float | None:
    expected = Decimal(match["exclusive"]) + Decimal(match["common"])
    # Some PDFs join two adjacent values. Do not turn that joined token into
    # a huge area, and never present a computed subtotal as a printed value.
    for token in match["areas"].split():
        value = re.fullmatch(r"\d{1,3}\.\d{2,6}", token)
        if value:
            parsed = Decimal(token)
            rounding = Decimal(5).scaleb(parsed.as_tuple().exponent - 1)
            if abs(parsed - expected) <= rounding:
                return float(parsed)
        elif token.count(".") > 1:
            # Recover an adjacent column only when the printed prefix equals
            # the expected subtotal and the remainder starts another area.
            printed = format(expected.normalize(), "f")
            if token.startswith(printed) and re.match(r"\d{1,3}\.\d", token[len(printed):]):
                return float(expected)
    return None


def _identity(payload: dict | None, whole: str, *, url: str, digest: str) -> bool:
    """Bind to the current publication, without replacing it by a prior date."""
    if not payload:
        return False
    title = str(payload.get("title") or "")
    # The date is shared by unrelated notices. Require a project name from
    # the listing in the attachment, ignoring generic sale and correction labels.
    words = set(re.findall(r"[가-힣A-Za-z0-9]{3,}", title)) - {
        "정정공고", "일반매각", "미분양매입", "공가세대", "잔여세대", "잔여주택",
        "선착순", "공급공고", "동호지정", "세대구성원", "무주택세대구성원", "계약가능", "유주택자",
    }
    compact = _compact(whole[:12000])
    if not words or not any(word in compact for word in words):
        return False
    contract = re.search(r"(?:기준일|신청자격)[^.]{0,130}?계약\s*체결일", whole)
    if contract and any(r.get("kind") == "qualification_context" and r.get("verification") == "official"
                        and r.get("source") == "official_document_parser" and r.get("document_hash") == digest
                        and r.get("evidence_url") == url
                        and r.get("value", {}).get("application_criterion_basis") == "contract_date"
                        for r in payload.get("rules", [])):
        return True
    cutoff = str(payload.get("announcement_date") or "")[:10]
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", cutoff):
        return False
    y, m, d = (int(p) for p in cutoff.split("-"))
    # The document may also cite the original project's date. A matching
    # current announcement statement, not an arbitrary date occurrence, binds.
    pattern = (r"(?:입주자\s*모집공고일|매각\s*공고일|모집공고일|공고일)"
               r"[^\d]{0,30}" + str(y) + r"[.년/-]\s*0?" + str(m)
               + r"[.월/-]\s*0?" + str(d) + r"(?:[.일\s(]|$)")
    return bool(re.search(pattern, whole))


def parse_price_tables(pages: list[dict], *, url: str, digest: str, payload: dict | None = None) -> dict:
    whole = _normal(" ".join(page["text"] for page in pages))
    sale = bool(re.search(r"일반\s*매각|분양\s*가격|매각\s*가격|주택\s*가격", whole))
    # A rental conversion described in the history does not make the present
    # sale amounts rental deposits. Conversely, actual rental tables are left
    # to their existing deposit/monthly parser.
    if not sale:
        return {"prices": [], "rules": [], "complete": False, "price_identity_confirmed": False}
    bound = _identity(payload, whole, url=url, digest=digest)
    if not bound:
        return {"prices": [], "rules": [], "complete": False, "price_identity_confirmed": False}
    fallback = str((payload or {}).get("title") or "")
    prices, details, costs = [], [], []
    seen = set()
    any_table = False
    rejected = 0
    site_by_area: dict[str, set[str]] = {}
    for page in pages:
        for match in ROW.finditer(page["text"]):
            line_start = page["text"].rfind("\n", 0, match.start()) + 1
            prefix = page["text"][line_start:match.start()]
            name = re.sub(r"\s+\d+\s*$", "", prefix).strip()
            if len(re.findall(r"[가-힣]", name)) >= 3 and len(name) < 80:
                site_by_area.setdefault(match["exclusive"], set()).add(name)
    for page in pages:
        text = page["text"]
        compact = _compact(text)
        headed = (bool(re.search(r"(?:분양|매각|주택)(?:가격|금액)(?:\(원\)|\[원\]|원)?", compact))
                  and "계약금" in compact and "잔금" in compact
                  and ("주거전용" in compact or "전용면적" in compact or "공급면적" in compact))
        if not headed:
            continue
        any_table = True
        matches = list(ROW.finditer(text))
        vertical = bool(re.search(r"(?:^|\n)동\s*\n호\s*\n", text))
        buildings = []
        if vertical:
            # A merged building cell is printed only once. The construction
            # year in a following column is not a new building number.
            buildings = [m for m in matches if not re.search(r"난방\s*$", text[max(0,m.start()-18):m.start()])]
            matches = list(ROOM_ROW.finditer(text))
        # Printed type markers sometimes sit in the middle of a merged cell.
        # Match them to a unique exclusive area instead of inheriting a prior
        # row's label across different units.
        area_types: dict[str, set[str]] = {}
        for match in matches:
            prefix = text[max(0, match.start()-18):match.start()]
            code = re.search(r"(?<![\w.])(\d{2,3}[A-Z](?:[A-Z])?)\s*$", prefix)
            if code:
                area_types.setdefault(match["exclusive"], set()).add(code[1])
        for match in matches:
            total, first, balance = (int(match[key].replace(",", "")) for key in ("total", "first", "balance"))
            interim = int(match["interim"].replace(",", "")) if match["interim"] else None
            if total < 1_000_000 or first + (interim or 0) + balance != total or interim is not None and "중도금" not in compact:
                rejected += 1
                continue
            exclusive = float(match["exclusive"])
            if not 10 <= exclusive <= 500:
                rejected += 1
                continue
            named = site_by_area.get(match["exclusive"], set())
            site = next(iter(named)) if len(named) == 1 else _site(text, match.start(), fallback)
            if vertical:
                previous = [m for m in buildings if m.start() <= match.start()]
                if not previous:
                    rejected += 1
                    continue
                building = previous[-1]["building"]
            else:
                building = match["building"]
            room = ", ".join(re.split(r"\s*[,·]\s*", match["room"]))
            codes = area_types.get(match["exclusive"], set())
            code = next(iter(codes)) if len(codes) == 1 else None
            label = f"{building}동 {room}호"
            if code:
                label = f"{code} · {label}"
            if site and site != fallback:
                label = f"{site} {label}"
            key = (site, building, room, exclusive)
            if key in seen:
                rejected += 1
                continue
            seen.add(key)
            eid = hashlib.sha256(json.dumps([site, building, room, exclusive], ensure_ascii=False).encode()).hexdigest()[:24]
            header_start = max(0, text.rfind("분양가격", 0, match.start()), text.rfind("주택가격", 0, match.start()))
            header = _normal(text[header_start:match.start()])[-450:]
            evidence = _evidence(url, digest, page, header + " / " + _normal(match[0]))
            components = [{"kind": kind, "label": name, "amount_krw": amount, **evidence}
                          for kind, name, amount in (("down_payment", "계약금", first),
                                                     ("interim_payment", "중도금", interim),
                                                     ("balance", "잔금", balance)) if amount is not None]
            prices.append({"unit_type": label[:120], "area_sqm": exclusive,
                           "price_kind": "sale_total", "amount_krw": total, "monthly_krw": None,
                           "basis_label": "동·호별 총분양가",
                           **{key: evidence[key] for key in ("verification", "document_hash", "evidence_url", "evidence_text")}})
            details.append({"unit_type": label[:120], "dwelling_identity": eid, "site_name": site or None,
                            "building": building, "room": room, "unit_type_code": code,
                            "amount_krw": total, "exclusive_area_sqm": exclusive,
                            "supply_area_sqm": _supply_area(match), "payment_components": components,
                            **evidence})
    # Fees have their own semantic header, cannot create a house or a rent row.
    for page in pages:
        text = _normal(page["text"])
        if "관리비" not in text or "예치금" not in text:
            continue
        table = re.search(r"단지\s*전용면적\s*관리비\s*예치금(.{0,600})", text)
        if not table:
            continue
        for match in re.finditer(r"([가-힣A-Za-z0-9][가-힣A-Za-z0-9 ·-]{2,70}?)\s+(\d{1,3}\.\d+)\s*㎡\s*(" + MONEY + r")\s*원", table[1]):
            name = match[1].strip()
            amount = int(match[3].replace(",", ""))
            if not 0 < amount < 10_000_000:
                continue
            costs.append({"kind": "management_deposit", "label": "관리비예치금", "site_name": name,
                          "exclusive_area_sqm": float(match[2]), "amount_krw": amount,
                          **_evidence(url, digest, page, match[0])})
    if not details and not costs:
        return {"prices": [], "rules": [], "complete": False, "price_identity_confirmed": bound}
    first = details[0] if details else costs[0]
    evidence = {key: first[key] for key in ("verification", "source", "parser_version", "price_parser_version", "document_hash", "evidence_url", "evidence_page", "evidence_text")}
    facts = []
    if details:
        facts.append(_rule("price_details", evidence, entries=details))
        facts.append(_rule("unit_exclusive_areas", evidence, units=[{"unit_type": d["unit_type"], "exclusive_area_sqm": d["exclusive_area_sqm"]} for d in details]))
    if costs:
        facts.append(_rule("additional_costs", evidence, entries=costs))
    facts.append(_rule("price_extraction", evidence, status="partial" if rejected else "complete",
                       dwelling_count=len(details), rejected_rows=rejected, price_table_found=any_table,
                       replaces_unverified=True, identity_confirmed=bound))
    return {"prices": prices, "rules": facts, "complete": not rejected,
            "price_identity_confirmed": bound}


def rebuild_document_prices(current: list[dict], parsed: list[dict], rules: list[dict], digest: str) -> list[dict]:
    """Rebuild stale derived candidates even for identical document bytes."""
    repair = any(r.get("kind") == "price_extraction" and r.get("document_hash") == digest
                 and r.get("price_parser_version") == PRICE_PARSER_VERSION
                 and r.get("identity_confirmed") is True and r.get("verification") == "official"
                 and r.get("source") == "official_document_parser" for r in rules)
    kept = [p for p in current if not (repair and p.get("document_hash") == digest and p.get("verification") in UNVERIFIED)]
    identities = {(p.get("unit_type"), p.get("price_kind"), p.get("document_hash")) for p in parsed}
    units = {p.get("unit_type") for p in parsed}
    kept = [p for p in kept if (p.get("unit_type"), p.get("price_kind"), p.get("document_hash")) not in identities
            and not (p.get("unit_type") in units and p.get("verification", "unknown") == "unknown"
                     and p.get("amount_krw") is None and p.get("monthly_krw") is None)]
    return kept + parsed
