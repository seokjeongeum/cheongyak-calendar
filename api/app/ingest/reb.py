"""한국부동산원 청약홈's five official detail/model API pairs.

Source: https://www.data.go.kr/data/15098547/openapi.do
The published Swagger defines LTTOT_TOP_AMOUNT and SUPLY_AMOUNT as 만원,
specifically the highest sale amount for a housing type. Rental amounts are
not interpreted as deposits unless the official announcement supplies that unit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from .common import FeedError, add_event, body_rows, date_iso, decimal_number, get_json, manwon_to_krw, omit_empty_enrichment, public_url, value

BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
SOURCE = "cheongyak_home"
CLASSIFICATION_SOURCE_URL = "https://www.data.go.kr/data/15098547/openapi.do"


@dataclass(frozen=True)
class Pair:
    detail: str
    model: str
    category: str


PAIRS = (
    Pair("getAPTLttotPblancDetail", "getAPTLttotPblancMdl", "apt"),
    Pair("getUrbtyOfctlLttotPblancDetail", "getUrbtyOfctlLttotPblancMdl", "urban"),
    Pair("getRemndrLttotPblancDetail", "getRemndrLttotPblancMdl", "unsold"),
    Pair("getPblPvtRentLttotPblancDetail", "getPblPvtRentLttotPblancMdl", "private_rental"),
    Pair("getOPTLttotPblancDetail", "getOPTLttotPblancMdl", "optional_supply"),
)


def _is_rental(raw: dict[str, Any], pair: Pair) -> bool:
    # HOUSE_SECD_NM is the operation's bundled label and includes 민간임대
    # even for an officetel sale. Only the actual subtype is discriminating.
    return _category(raw, pair) == "private_rental" or str(raw.get("RENT_SECD") or "") == "1"


def _category(raw: dict[str, Any], pair: Pair) -> str:
    if pair.category != "urban":
        return pair.category
    by_code = {
        "0201": "urban", "0202": "officetel", "0203": "private_rental",
        "0204": "living_accommodation", "0303": "private_rental",
    }
    code = str(raw.get("SEARCH_HOUSE_SECD") or "")
    if code in by_code:
        return by_code[code]
    detail_code = str(raw.get("HOUSE_DTL_SECD") or "").zfill(2)
    subtype = {"01": "urban", "02": "officetel", "03": "private_rental", "04": "living_accommodation"}.get(detail_code)
    if subtype:
        return subtype
    name = str(raw.get("HOUSE_DTL_SECD_NM") or "")
    if "오피스텔" in name:
        return "officetel"
    if "임대" in name:
        return "private_rental"
    if "숙박" in name:
        return "living_accommodation"
    return "urban"


def _events(raw: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    add_event(events, "special", "특별공급", raw.get("SPSPLY_RCEPT_BGNDE"), raw.get("SPSPLY_RCEPT_ENDDE"))
    for rank, kind, label in ((1, "first_priority", "1순위"), (2, "second_priority", "2순위")):
        for stem, audience in (("CRSPAREA", "해당지역"), ("ETC_GG", "기타경기"), ("ETC_AREA", "기타지역")):
            prefix = f"GNRL_RNK{rank}_{stem}_"
            add_event(events, kind, label, raw.get(prefix + "RCPTDE"), raw.get(prefix + "ENDDE"), audience)
    add_event(events, "general", "일반공급", raw.get("GNRL_RCEPT_BGNDE"), raw.get("GNRL_RCEPT_ENDDE"))
    if not any(event["kind"] in ("special", "first_priority", "second_priority", "general") for event in events):
        add_event(events, "general", "청약 접수", value(raw, "SUBSCRPT_RCEPT_BGNDE", "RCEPT_BGNDE"), value(raw, "SUBSCRPT_RCEPT_ENDDE", "RCEPT_ENDDE"))
    add_event(events, "announcement", "당첨자 발표", raw.get("PRZWNER_PRESNATN_DE"))
    add_event(events, "contract", "계약", raw.get("CNTRCT_CNCLS_BGNDE"), raw.get("CNTRCT_CNCLS_ENDDE"))
    return events


def _yes_no(raw: Any) -> bool | None:
    text = str(raw or "").strip().upper()
    return True if text == "Y" else False if text == "N" else None


def _capital_region(raw: dict[str, Any]) -> bool | None:
    # SUBSCRPT_AREA_CODE is a source-specific code, not a legal-dong code.
    # Use its explicit official province label instead of guessing code prefixes.
    name = str(raw.get("SUBSCRPT_AREA_CODE_NM") or "").strip()
    province = name.split()[0] if name else ""
    if province in {"서울", "서울특별시", "인천", "인천광역시", "경기", "경기도"}:
        return True
    if province in {"부산", "부산광역시", "대구", "대구광역시", "광주", "광주광역시", "대전", "대전광역시", "울산", "울산광역시", "세종", "세종특별자치시", "강원", "강원도", "강원특별자치도", "충북", "충청북도", "충남", "충청남도", "전북", "전라북도", "전북특별자치도", "전남", "전라남도", "전남광주통합특별시", "경북", "경상북도", "경남", "경상남도", "제주", "제주특별자치도"}:
        return False
    return None


def _qualification_metadata(raw: dict[str, Any], pair: Pair, official_url: str | None) -> list[dict[str, Any]]:
    # Codes are endpoint-specific: urban 03 means 민간임대, not 국민주택.
    apt = pair.detail == "getAPTLttotPblancDetail"
    code = str(raw.get("HOUSE_DTL_SECD") or "").strip()
    category = _category(raw, pair)
    housing_kind = {"01": "private", "03": "national"}.get(code, "unknown") if apt else "not_applicable" if category in {"officetel", "living_accommodation"} else "unknown"
    evidence_url = official_url or CLASSIFICATION_SOURCE_URL
    context = {
        "public_housing": None,
        "speculation_zone": _yes_no(raw.get("SPECLT_RDN_EARTH_AT")) if apt else None,
        "subscription_overheated": _yes_no(raw.get("MDAT_TRGET_AREA_SECD")) if apt else None,
        "weakened_area": None,
        "capital_region": _capital_region(raw),
        "rule_effective_date": None,
        "original_announcement_date": date_iso(raw.get("RCRIT_PBLANC_DE")),
        # These exact published meanings must not be treated as 공공주택 여부.
        "public_housing_district": _yes_no(raw.get("PUBLIC_HOUSE_EARTH_AT")) if apt else None,
        "public_housing_special_law": _yes_no(raw.get("PUBLIC_HOUSE_SPCLW_APPLC_AT")) if apt else None,
        "capital_private_public_housing_district": _yes_no(raw.get("NPLN_PRVOPR_PUBLIC_HOUSE_AT")) if apt else None,
    }
    result = [{
        "kind": "housing_classification", "effect": "metadata", "housing_kind": housing_kind,
        "verification": "official" if housing_kind != "unknown" else "unknown", "source": SOURCE,
        "evidence_url": evidence_url,
        "evidence_text": f"{pair.detail}: HOUSE_DTL_SECD={code or '미공개'} (APT 주택상세구분 01: 민영, 03: 국민)" if apt else f"{pair.detail}: HOUSE_DTL_SECD={code or '미공개'}, SEARCH_HOUSE_SECD={raw.get('SEARCH_HOUSE_SECD') or '미공개'} ({category})",
    }, {
        "kind": "qualification_context", "effect": "metadata", "value": context,
        "verification": "official", "source": SOURCE, "evidence_url": evidence_url,
        "evidence_text": "; ".join(f"{field}={raw.get(field) if raw.get(field) is not None else '미공개'}" for field in ("SUBSCRPT_AREA_CODE_NM", "SPECLT_RDN_EARTH_AT", "MDAT_TRGET_AREA_SECD", "PUBLIC_HOUSE_EARTH_AT", "PUBLIC_HOUSE_SPCLW_APPLC_AT", "NPLN_PRVOPR_PUBLIC_HOUSE_AT")),
    }]
    ranked = apt and any(e["kind"] in {"first_priority", "second_priority"} for e in _events(raw))
    shinhee = apt and "신혼희망타운" in str(raw.get("HOUSE_DTL_SECD_NM") or "")
    if ranked or shinhee or pair.category in {"unsold", "optional_supply"} or category in {"officetel", "living_accommodation"}:
        result.append({"kind": "rank_applicability", "effect": "metadata", "status": "applicable" if ranked else "not_applicable",
                       "account_required": True if apt else False if category in {"officetel", "living_accommodation"} else None,
                       "reason": "아파트 일반공급 1·2순위 적용" if ranked else "신혼희망타운 별도 신청자격 적용" if shinhee else "오피스텔·생활숙박시설은 아파트 1·2순위 적용 없음" if category in {"officetel", "living_accommodation"} else "무순위·임의공급은 아파트 1·2순위 적용 없음",
                       "verification": "official", "source": SOURCE, "evidence_url": evidence_url,
                       "evidence_text": f"{pair.detail}: HOUSE_DTL_SECD={code or '미공개'}, HOUSE_MANAGE_NO={raw.get('HOUSE_MANAGE_NO')}"})
    # The bundled remainder operation includes more than one legal method.
    # Only a document can distinguish 사후/임의/계약취소; official rank dates
    # and the explicit officetel subtype can identify these two methods.
    method = "apt_ranked" if ranked else "officetel" if category == "officetel" else None
    if method:
        result.append({"kind": "application_method", "effect": "metadata", "value": method,
                       "verification": "official", "source": SOURCE, "evidence_url": evidence_url,
                       "criterion_date": date_iso(raw.get("RCRIT_PBLANC_DE")),
                       "evidence_text": f"{pair.detail}: HOUSE_DTL_SECD={code or '미공개'}, 일반공급 순위 일정 {'확인' if ranked else '적용 없음'}"})
    return result


def _prices(models: list[dict[str, Any]], raw: dict[str, Any], pair: Pair, evidence_url: str | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    rental = _is_rental(raw, pair)
    for model in models:
        unit = value(model, "HOUSE_TY", "TP", "MODEL_NO")
        if unit is None:
            continue
        unit_name = str(unit)
        group = value(model, "GP")
        if group and str(group) != unit_name:
            unit_name = f"{group} {unit_name}"
        area = decimal_number(value(model, "EXCLUSE_AR", "SUPLY_AR"))
        amount_field = "SUPLY_AMOUNT" if pair.category in ("urban", "private_rental") else "LTTOT_TOP_AMOUNT"
        amount = manwon_to_krw(model.get(amount_field))
        if amount == 0:
            amount = None
        # The API names rental SUPLY_AMOUNT a highest *sale* amount; it is not a
        # documented deposit or monthly rent. Keep it absent rather than relabel.
        if rental:
            amount = None
        result.append({
            "unit_type": unit_name,
            "area_sqm": float(area) if area is not None else None,
            "price_kind": "deposit" if rental else "sale_max",
            "amount_krw": amount,
            "monthly_krw": None,
            "basis_label": "공고문에서 임대조건 확인 필요" if rental else "타입별 최고 공급금액 · 부가세 포함" if _category(raw, pair) == "officetel" else "주택형별 최고 분양금액",
            "verification": "unknown" if rental else ("official" if amount is not None else "unknown"),
            "evidence_url": evidence_url,
            "evidence_text": f"{amount_field}={model.get(amount_field)} (단위: 만원)" if amount is not None else None,
        })
    return result


def _offered_supplies(models: list[dict[str, Any]], raw: dict[str, Any], pair: Pair, evidence_url: str | None) -> dict[str, Any] | None:
    # SUPLY_HSHLDCO is general supply, never a total to copy into a synthetic
    # general row. Each special column is an independently offered scope.
    columns = {
        "SUPLY_HSHLDCO": "일반공급", "INSTT_RECOMEND_HSHLDCO": "기관추천 특별공급",
        "MNYCH_HSHLDCO": "다자녀가구 특별공급", "NWWDS_HSHLDCO": "신혼부부 특별공급",
        "OLD_PARNTS_SUPORT_HSHLDCO": "노부모부양 특별공급", "LFE_FRST_HSHLDCO": "생애최초 특별공급",
        "NEWBORN_HSHLDCO": "신생아 특별공급", "TRANSR_INSTT_ENFSN_HSHLDCO": "이전기관종사자 특별공급",
    }
    supplied = any(any(key in model for key in columns) for model in models)
    if not supplied or _is_rental(raw, pair):
        return None
    rows = []
    for model in models:
        unit = value(model, "HOUSE_TY", "TP", "MODEL_NO")
        if unit is None:
            continue
        for field, supply in columns.items():
            number = decimal_number(model.get(field))
            if number is None or number <= 0 or number != int(number):
                continue
            rows.append({"supply_type": supply, "unit_type": str(unit), "supply_count": int(number),
                         "verification": "official", "evidence_url": evidence_url,
                         "evidence_text": f"{pair.model}: HOUSE_TY={unit}, {field}={model[field]}",
                         "criterion_date": date_iso(raw.get("RCRIT_PBLANC_DE"))})
    return {"kind": "offered_supplies", "effect": "metadata", "verification": "official", "source": SOURCE,
            "supplies": rows, "inventory_complete": True, "evidence_url": evidence_url,
            "evidence_text": f"{pair.model}: 주택형별 일반·특별공급 모집 세대수"}


def normalize(detail: dict[str, Any], models: list[dict[str, Any]], pair: Pair) -> dict[str, Any] | None:
    house_no = value(detail, "HOUSE_MANAGE_NO")
    notice_no = value(detail, "PBLANC_NO")
    title = value(detail, "HOUSE_NM")
    if house_no is None or notice_no is None or title is None:
        return None
    official_url = public_url(value(detail, "PBLANC_URL", "HMPG_ADRES"))
    cap = str(detail.get("PARCPRC_ULS_AT") or "").upper().strip()
    payload: dict[str, Any] = {
        "source": SOURCE,
        "external_id": f"{pair.detail}:{house_no}:{notice_no}",
        "title": str(title),
        "provider": str(value(detail, "BSNS_MBY_NM", "NSPRC_NM") or "한국부동산원 청약홈"),
        "category": _category(detail, pair),
        "address": value(detail, "HSSPLY_ADRES"),
        "region_code": value(detail, "SUBSCRPT_AREA_CODE"),
        "region_name": value(detail, "SUBSCRPT_AREA_CODE_NM"),
        "announcement_date": date_iso(detail.get("RCRIT_PBLANC_DE")),
        "official_url": official_url,
        "price_cap_status": "yes" if cap == "Y" else "no" if cap == "N" else "unknown" if pair.category in ("apt", "unsold") else "not_applicable",
        "events": _events(detail),
        "prices": _prices(models, detail, pair, official_url),
        "rules": _qualification_metadata(detail, pair, official_url),
        "rules_complete": False,
    }
    fees = []
    exclusive = []
    inventory = _offered_supplies(models, detail, pair, official_url)
    if inventory:
        payload["rules"].append(inventory)
    for model in models:
        area = decimal_number(model.get("EXCLUSE_AR"))
        price = _prices([model], detail, pair, official_url)
        if area is not None and price:
            exclusive.append({"unit_type": price[0]["unit_type"], "exclusive_area_sqm": float(area)})
    if exclusive:
        payload["rules"].append({"kind": "unit_exclusive_areas", "effect": "metadata", "verification": "official", "source": SOURCE,
                                 "units": exclusive, "evidence_url": official_url or CLASSIFICATION_SOURCE_URL, "evidence_text": f"{pair.model}: EXCLUSE_AR (전용면적, ㎡)"})
    if pair.category == "urban":
        for model in models:
            amount = manwon_to_krw(model.get("SUBSCRPT_REQST_AMOUNT"))
            unit = value(model, "TP", "HOUSE_TY", "MODEL_NO")
            if amount is not None and unit is not None:
                fees.append({"unit_type": str(unit), "application_fee_krw": amount})
        if fees:
            payload["rules"].append({"kind": "supply_financial_terms", "effect": "metadata", "verification": "official", "source": SOURCE,
                                     "units": fees, "evidence_url": official_url or CLASSIFICATION_SOURCE_URL,
                                     "evidence_text": f"{pair.model}: SUBSCRPT_REQST_AMOUNT (단위: 만원), 분양금액과 별도인 청약신청금"})
    return omit_empty_enrichment(payload)


async def _pages(client: httpx.AsyncClient, url: str, params: dict[str, Any], *, max_pages: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        request = {**params, "page": page, "perPage": 100, "returnType": "JSON"}
        body = await get_json(client, url, request)
        batch, total = body_rows(body, "data")
        rows.extend(batch)
        if not batch or (total is not None and len(rows) >= total) or len(batch) < 100:
            return rows
    raise FeedError("청약홈 페이지 상한 초과")


async def collect(client: httpx.AsyncClient, key: str, start: date, end: date) -> list[dict[str, Any]]:
    """Fetch nationwide notices published in the inclusive announcement window."""
    all_notices: list[dict[str, Any]] = []
    for pair in PAIRS:
        details = await _pages(client, f"{BASE}/{pair.detail}", {
            "serviceKey": key,
            "cond[RCRIT_PBLANC_DE::GTE]": start.isoformat(),
            "cond[RCRIT_PBLANC_DE::LTE]": end.isoformat(),
        })
        for detail in details:
            house_no = value(detail, "HOUSE_MANAGE_NO")
            notice_no = value(detail, "PBLANC_NO")
            if house_no is None or notice_no is None:
                continue
            models = await _pages(client, f"{BASE}/{pair.model}", {
                "serviceKey": key,
                "cond[HOUSE_MANAGE_NO::EQ]": house_no,
                "cond[PBLANC_NO::EQ]": notice_no,
            }, max_pages=20)
            normalized = normalize(detail, models, pair)
            if normalized:
                all_notices.append(normalized)
    return all_notices
