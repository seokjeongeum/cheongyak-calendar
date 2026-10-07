"""Conservative, local parsing of explicitly stated official announcement facts.

This parser does not turn an LLM quotation into a verified interpretation. It
recognizes reviewed announcement sections and explicit units/operators only.
Unmatched requirements and legal exceptions leave the scope incomplete. Each
fact keeps its page/section, source document hash, parser version and cutoff.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .reviewed_sources import REVIEWED_SOURCES
from .unranked_rules import parse_unranked_conditions

PARSER_VERSION = "official-sections-2026-10-07-v8"
COMPATIBLE_ORDINARY_PARSER_VERSION = "official-sections-2026-10-04-v3"
SPECIAL_NAMES = ("기관추천", "다자녀가구", "신혼부부", "노부모부양", "생애최초", "신생아", "청년", "이전기관종사자", "협의양도인", "철거주택소유자", "지역균형발전", "일반(기관추천)")
PROVINCES = {
    "서울특별시": "11", "부산광역시": "26", "대구광역시": "27", "인천광역시": "28",
    "광주광역시": "29", "대전광역시": "30", "울산광역시": "31", "세종특별자치시": "36",
    "경기도": "41", "강원특별자치도": "51", "충청북도": "43", "충청남도": "44",
    "전북특별자치도": "52", "전라남도": "46", "경상북도": "47", "경상남도": "48", "제주특별자치도": "50",
}


def parser_version_usable(rule: dict, *, category: str = "", title: str = "", rules: list[dict] | None = None) -> bool:
    if rule.get("source") != "official_document_parser" or rule.get("parser_version") == PARSER_VERSION:
        return True
    # v8 adds supply-scoped special selection metadata. Prior admission facts
    # remain valid until their document is reparsed/corrected.
    if rule.get("parser_version") in {"official-sections-2026-10-05-v5", "official-sections-2026-10-05-v6", "official-sections-2026-10-05-v7"}:
        return True
    # Retain compatible ordinary rank/ownership/office facts during reprocessing,
    # while retiring the old early-return interpretation for affected offers.
    affected = category in {"unsold", "optional_supply"} or bool(re.search(r"무순위|임의\s*공급|불법행위\s*재공급|계약\s*취소.*재공급", title)) or any(
        r.get("kind") == "application_method" and r.get("value") in {"unranked_after", "optional_supply", "cancelled_resupply"}
        for r in rules or []
    )
    return rule.get("parser_version") in {COMPATIBLE_ORDINARY_PARSER_VERSION, "official-sections-2026-10-04-v4"} and not affected


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def normal(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _province_scopes(sentence: str) -> list[str]:
    """Only explicit whole-province scopes, never a province-qualified city."""
    text = compact(sentence)
    names = [name for name in PROVINCES if name in text]
    if not names:
        return []
    grouped = re.search(r"수도권[\[(]([^\])]+)[\])](?:에|에서)?거주", text)
    if grouped:
        body = grouped.group(1)
        group_names = [name for name in names if name in body]
        # An explicit 수도권 grouping identifies provinces. A city, county or
        # district following a province name narrows it and cannot be widened.
        if group_names and all(re.search(re.escape(name) + r"(?=[·,ㆍ\]）)「]|$)", body) for name in group_names) and set(group_names) == set(names):
            return group_names
        return []
    return names if all(re.search(re.escape(name) + r"(?:에|에서)?거주", text) for name in names) else []


def application_method(pages: list[dict]) -> tuple[str, dict | None]:
    """Only an actual document heading establishes a nonstandard method.

    A general APT document can mention later residual/first-come contracts or
    other application methods in its instructions. Those are not this offer.
    """
    patterns = (
        ("officetel", r"오피스텔\s*(?:분양광고|분양공고)"),
        ("cancelled_resupply", r"(?:불법행위\s*재공급|계약\s*취소(?:\s*주택)?\s*재공급)\s*입주자\s*모집공고"),
        ("unranked_after", r"무순위\s*\(?\s*사후\s*\)?\s*입주자\s*모집공고"),
        ("optional_supply", r"임의\s*공급\s*(?:입주자)?\s*모집공고"),
        ("first_come", r"(?:선착순\s*(?:동[·ㆍ]?호\s*지정|계약|일반매각)|\(선착순)"),
    )
    for page in pages[:2]:
        header = normal(page["text"][:1100])
        for value, pattern in patterns:
            found = re.search(pattern, header)
            if found:
                return value, {"page": page["page"], "text": found.group(0)}
    return "unknown", None


def document_cutoff(pages: list[dict], *, method: str = "unknown") -> tuple[str | None, dict | None]:
    """Only an explicit statement of the qualification announcement cutoff."""
    if method in {"unranked_after", "optional_supply", "cancelled_resupply"}:
        method_name = r"무순위\s*\(?사후\)?" if method == "unranked_after" else r"임의\s*공급" if method == "optional_supply" else r"(?:불법행위\s*재공급|계약\s*취소(?:\s*주택)?\s*재공급)"
        current = re.compile(r"(?:본\s*(?:주택의\s*)?)?" + method_name + r"\s*입주자\s*모집공고일[은는]\s*(?:\([^)]{0,3}\)\s*)?(20\d{2})[.년\-/]\s*(\d{1,2})[.월\-/]\s*(\d{1,2})")
        for page in pages[:8]:
            match = current.search(normal(page["text"]))
            if match:
                try:
                    return date(*(int(v) for v in match.groups())).isoformat(), {"page": page["page"], "text": match.group(0)}
                except ValueError:
                    pass
        # The schedule table may put the labels before the dates, with PDF
        # extraction moving weekday labels ahead of the date columns.
        for page in pages[:3]:
            body = normal(page["text"])
            schedule = re.search(r"구분\s*최초[^■]{0,60}?무순위\s*사후[^■]{0,260}?입주자모집공고일[^■]{0,100}?일정[^■]{0,210}", body)
            if schedule:
                dates = re.findall(r"20\d{2}\.\d{2}\.\d{2}", schedule.group(0))
                if len(dates) >= 2:
                    try:
                        return date.fromisoformat(dates[1].replace(".", "-")).isoformat(), {"page": page["page"], "text": schedule.group(0)}
                    except ValueError:
                        pass
        # An original project's date is not the new application's cutoff.
        return None, None
    # A divided offering has a fresh qualification date for this round.
    for page in pages[:8]:
        text = normal(page["text"])
        round_date = re.search(r"본\s*주택의\s*(?:\d+\s*회차|회차)\s*입주자모집공고일은\s*(?:\d+\s*)?(20\d{2})[.년\-/]\s*(\d{1,2})[.월\-/]\s*(\d{1,2})", text)
        if round_date:
            try:
                return date(*(int(v) for v in round_date.groups())).isoformat(), {"page": page["page"], "text": round_date.group(0)}
            except ValueError:
                pass
    for page in pages[:8]:
        text = normal(page["text"])
        match = re.search(r"(?:(?:이\s*주택의|본\s*주택의)\s*(?:최초\s*)?입주자모집공고일[은는]\s*|분양광고일\s*\()(20\d{2})[.년\-/]\s*(\d{1,2})[.월\-/]\s*(\d{1,2})", text)
        if match:
            try:
                cutoff = date(*(int(v) for v in match.groups())).isoformat()
                return cutoff, {"page": page["page"], "text": match.group(0)}
            except ValueError:
                continue
    return None, None


def _section_heading(line: str, shinhee: bool) -> str | None:
    line = normal(line)
    # Numbered section headings, not schedule/table mentions or explanatory
    # sentences elsewhere in the document, establish the offered inventory.
    match = re.match(r"^\d+(?:[-.]\d+)?\.?\s+(.+)$", line)
    if not match:
        return None
    title = compact(match.group(1))
    if title.startswith("일반공급") and (len(title) < 12 or "주택공급에관한규칙" in title):
        return "일반공급"
    for name in SPECIAL_NAMES:
        if title.startswith(name + "특별공급"):
            return name + " 특별공급"
    if shinhee:
        for name in ("신혼부부", "예비신혼부부", "한부모가족"):
            if title.startswith(name + "신청자격"):
                return name + "(신혼희망타운)"
    return None


def _sections(pages: list[dict], shinhee: bool) -> list[dict]:
    sections: list[dict] = []
    current: dict | None = None
    for page in pages:
        for line in page["text"].splitlines():
            title = _section_heading(line, shinhee)
            if title:
                current = {"supply_type": title, "page": page["page"], "lines": []}
                sections.append(current)
            elif re.match(r"^\d+(?:[-.]\d+)?(?:\.\s*|\s+)[가-힣A-Z]", normal(line)):
                current = None
            if current is not None:
                current["lines"].append({"page": page["page"], "text": line})
    # An repeated heading in a contents listing is not allowed to override the
    # actual target section. Require a target/applicant qualification body.
    return [s for s in sections if re.search(r"대상자|신청자격|아래\s*조건|자격요건|입주자모집공고일\s*현재", "\n".join(l["text"] for l in s["lines"]))]


def _deposit_table(lines: list[dict]) -> tuple[list[dict], dict | None]:
    for index, line in enumerate(lines):
        if "청약예금의예치금액" not in compact(line["text"]):
            continue
        following = lines[index:index + 15]
        joined = normal(" ".join(l["text"] for l in following))
        if not all(v in compact(joined) for v in ("특별시및부산광역시", "그밖의광역시", "특별시및광역시를제외한지역")):
            return [], None
        rows = []
        for following_line in following:
            match = re.search(r"(?:전용면적(?:이하)?(\d+)[㎡m²]+(?:이하)?|(모든면적))([\d,]+)만원([\d,]+)만원([\d,]+)만원", compact(following_line["text"]))
            if match:
                area = int(match.group(1)) if match.group(1) else None
                values = [int(v.replace(",", "")) * 10_000 for v in match.groups()[2:]]
                rows.append({"max_area_sqm": area, "amounts_krw": dict(zip(("seoul_busan", "other_metropolitan", "other"), values))})
        if [r["max_area_sqm"] for r in rows] != [85, 102, 135, None]:
            return [], None
        return rows, {"page": line["page"], "text": joined[:900]}
    return [], None


def parse_official_rules(pages: list[dict], *, url: str, digest: str, payload: dict | None = None) -> dict:
    from .contract_schedule import parse_contract_schedule
    result = _parse_official_rules(pages, url=url, digest=digest, payload=payload)
    contract = parse_contract_schedule(pages, url=url, digest=digest, parser_version=PARSER_VERSION)
    if contract:
        context_rule = next((r for r in result.get("rules", []) if "criterion_date" in r), None)
        contract["criterion_date"] = context_rule.get("criterion_date") if context_rule else None
        contract["criterion_basis"] = context_rule.get("criterion_basis") if context_rule else None
        result["rules"] = [r for r in result.get("rules", []) if r.get("kind") != "contract_schedule"] + [contract]
        result["contract_schedule"] = {k: contract.get(k) for k in (
            "status", "start_date", "end_date", "verification", "source", "evidence_url", "evidence_text", "evidence_page", "document_hash")}
    from .selection_rules import parse_selection_rules
    # The independent EXCLUSE_AR API field remains usable when a PDF's visual
    # supply table separates the dwelling code and area into different columns.
    # Stale document interpretations cannot supplement a corrected attachment.
    area_rules = [r for r in (payload or {}).get('rules', []) if r.get('kind') == 'unit_exclusive_areas'
                  and r.get('verification') == 'official' and (r.get('source') == 'cheongyak_home'
                  or r.get('source') == 'official_document_parser' and r.get('document_hash') == digest)]
    result['rules'].extend(parse_selection_rules(pages, url=url, digest=digest, rules=[*result.get('rules', []), *area_rules], parser_version=PARSER_VERSION))
    return result


def _parse_official_rules(pages: list[dict], *, url: str, digest: str, payload: dict | None = None) -> dict:
    payload = payload or {}
    pages = [{"page": int(p["page"]), "text": str(p["text"]), "source_format": p.get("source_format", "pdf_page")} for p in pages]
    from .public_sale_rules import parse_public_sale_rules
    public_offer = parse_public_sale_rules(pages, url=url, digest=digest, payload=payload, parser_version=PARSER_VERSION)
    if public_offer is not None:
        return public_offer
    method, method_evidence = application_method(pages)
    cutoff, cutoff_evidence = document_cutoff(pages, method=method)
    text = "\n".join(p["text"] for p in pages)
    flat = compact(text)
    reviewed = next((s for s in REVIEWED_SOURCES.values() if s["document_hash"] == digest and s["document_url"] == url), None)
    if cutoff is None and reviewed and reviewed.get("regional_review"):
        # Reviewed qualification table: the current date can be drawn after
        # the weekday or after a second-round label in the PDF stream.
        expected = reviewed["announcement_date"]
        for source_page in pages[:8]:
            normalized = normal(source_page["text"])
            dates = []
            for y,m,d in re.findall(r"(20\d{2})[.년]\s*(\d{1,2})[.월]\s*(\d{1,2})", normalized):
                try:
                    dates.append(date(int(y), int(m), int(d)).isoformat())
                except ValueError:
                    continue
            if expected in dates and re.search(r"입주자모집공고일|회차.*모집공고|무순위.*사후", normalized):
                cutoff, cutoff_evidence = expected, {"page": source_page["page"], "text": normalized[:900]}
                break
    # A correction may have a new publication date. Only the explicitly stated
    # original cutoff is used, and conflicting source context blocks parsing.
    original = next((r.get("value", {}).get("original_announcement_date") for r in payload.get("rules", []) if r.get("kind") == "qualification_context"), None)
    nonrank_apt = method in {"unranked_after", "optional_supply", "cancelled_resupply"}
    previous_application = next((r.get("value", {}).get("application_criterion_date") for r in payload.get("rules", []) if r.get("kind") == "qualification_context"), None)
    expected_cutoff = previous_application or payload.get("announcement_date") if nonrank_apt else original or payload.get("announcement_date")
    context_conflict = bool(expected_cutoff and cutoff and str(expected_cutoff)[:10] != cutoff)
    # A reviewed correction file may retain its original qualification cutoff
    # while its source record's publication date changes. Only the exact
    # reviewed document identity/hash can resolve that disagreement.
    if context_conflict and not original:
        known = next((s for s in REVIEWED_SOURCES.values() if s["document_hash"] == digest and s["document_url"] == url and s["announcement_date"] == cutoff), None)
        if known and "정정" in str(payload.get("title", "")):
            context_conflict = False
    manage_no = (parse_qs(urlparse(str(payload.get("official_url", ""))).query).get("houseManageNo") or [None])[0]
    if manage_no and manage_no not in flat and not reviewed:
        context_conflict = True
    official_kind = next((r.get("housing_kind") for r in payload.get("rules", []) if r.get("kind") == "housing_classification" and r.get("verification") == "official"), None)
    private = bool(re.search(r"민영주택으로|민영주택입주자모집공고", flat)) or bool(nonrank_apt and reviewed and reviewed.get("housing_kind") == "private" and re.search(r"주택유형[^■]{0,100}민영|주택구분[^■]{0,300}민영", flat[:15000]))
    national = bool(re.search(r"「주택법」에의한국민주택|주택유형국민|국민주택입주자모집공고", flat))
    kind = "private" if private and not national else "national" if national and not private else official_kind if official_kind in ("private", "national") else "unknown"
    office = payload.get("category") in {"officetel", "living_accommodation"} or bool(re.search(r"오피스텔(?:분양광고|분양공고)", flat[:5000])) or ("오피스텔" in str(payload.get("title", "")) and "오피스텔" in flat[:1000])
    outside_apt = office and (bool(re.search(r"본오피스텔|본생활숙박시설", flat[:6000])) or "오피스텔" in flat[:1000])
    first_come = method == "first_come"
    unranked = nonrank_apt or payload.get("category") in {"unsold", "optional_supply"}
    if outside_apt:
        kind = "not_applicable"
    classified = kind != "unknown" and not (official_kind and official_kind != kind)
    rules: list[dict] = []
    if context_conflict or (not cutoff and not (first_come or unranked)) or ("입주자모집공고" not in flat and not outside_apt and not first_come) or (not classified and not outside_apt and not first_come and not unranked):
        return {"rules": [], "offered_supply_types": [], "status": "unsupported", "reason": "공식 주택 구분·기준일 또는 문서 맥락을 확인하지 못했습니다."}

    def make(kind_name: str, value=None, *, supply=None, quote="", page=None, **fields) -> dict:
        identity = json.dumps([digest, kind_name, supply, quote, fields], ensure_ascii=False, sort_keys=True)
        result = {"id": "official-" + hashlib.sha256(identity.encode()).hexdigest()[:16], "kind": kind_name,
                  "verification": "official", "source": "official_document_parser", "parser_version": PARSER_VERSION,
                  "document_hash": digest, "evidence_url": url, "evidence_text": normal(quote)[:900], "evidence_page": page,
                  "criterion_date": cutoff, "criterion_basis": "announcement", "housing_kind": kind, **fields}
        if page and any(p["page"] == page and p["source_format"] == "hwpx_section" for p in pages):
            result["evidence_section"] = page
            result["evidence_page"] = None
        if "주택공급에관한규칙" in flat:
            result["applicable_law"] = "주택공급에 관한 규칙"
        if kind == "national" and "공공주택특별법시행규칙" in flat:
            result["applicable_law"] = "공공주택 특별법 시행규칙 및 주택공급에 관한 규칙"
        if value is not None:
            result["value"] = value
        if supply:
            result["supply_type"] = supply
        return result

    def exceptional(rule: dict, description: str, source_text: str) -> dict:
        # An unsupported official exception can turn a base failure into review;
        # it never independently grants eligibility.
        keyword = "출산특례" if "출산특례" in description else "장기복무" if "장기복무" in description else "재혼" if "재혼" in description else "청약통장 불필요" if "통장 불필요" in description else "세액공제" if "소득세" in description else "혼인신고" if "혼인 전" in description else "예비신혼부부"
        anchor = next((p for p in pages if keyword in normal(p["text"])), None)
        anchor_text = normal(anchor["text"]) if anchor else rule["evidence_text"]
        offset = max(0, anchor_text.find(keyword) - 100) if anchor else 0
        rule["exceptions"] = [make("unparsed", quote=anchor_text[offset:offset + 850], page=anchor["page"] if anchor else rule["evidence_page"], text=description, label=description)]
        return rule

    from .regional_rules import regional_supplement, residual_special_conditions
    regional = regional_supplement(pages, reviewed=reviewed, cutoff=cutoff, make=make)

    if method != "unknown":
        rules.append(make("application_method", method, effect="metadata", quote=method_evidence["text"], page=method_evidence["page"]))

    if outside_apt or first_come or unranked:
        # These application methods have no apartment first/second rank.
        # Keep an apartment's official private/national kind when it is known;
        # only a true non-APT building receives not_applicable housing kind.
        anchor = next((p for p in pages if re.search(r"청약통장[^\n]{0,80}(?:필요하지|무관)|선착순|무순위", p["text"])), pages[0])
        no_account = bool(re.search(r"청약통장(?:가입여부와)?(?:무관|관계없이|[^。■]{0,60}필요하지않)|청약통장이?필요없", flat))
        reason = "오피스텔 · 청약통장 불필요 · 아파트 1·2순위 적용 없음" if outside_apt and no_account else "선착순 계약 · 아파트 1·2순위 적용 없음" if first_come else "계약취소 후 재공급 · 아파트 1·2순위 적용 없음" if method == "cancelled_resupply" else "무순위·임의공급 · 아파트 1·2순위 적용 없음"
        rules.append(make("rank_applicability", effect="metadata", status="not_applicable", account_required=False if no_account else None, reason=reason, quote=normal(anchor["text"])[:850], page=anchor["page"]))
        if kind != "unknown":
            rules.append(make("housing_classification", effect="metadata", quote=normal(pages[0]["text"])[:700], page=pages[0]["page"]))
        prices = []
        offered = ["일반공급"]
        if reviewed and reviewed.get("sale_prices"):
            # Exact document hash review binds row/column interpretation,
            # VAT and highest-floor prices. A changed table is never reused.
            for row in reviewed["sale_prices"]:
                prices.append({**row, "price_kind": "sale_max", "monthly_krw": None,
                               "basis_label": "타입별 최고 공급금액 · 부가세 포함", "verification": "official", "document_hash": digest,
                               "evidence_url": url, "evidence_text": f"공고문 2쪽 공급금액(원) 계의 타입별 최고금액: {row['unit_type']} {row['amount_krw']:,}원 · 3쪽 부가세 포함"})
            terms = make("supply_financial_terms", effect="metadata", quote=next(p["text"] for p in pages if p["page"] == 5)[:850], page=5,
                         units=[{"unit_type": r["unit_type"], "application_fee_krw": reviewed["application_fee_krw"]} for r in reviewed["sale_prices"]])
            rules.append(terms)
            rules.append(make("unit_exclusive_areas", effect="metadata", units=[{"unit_type": r["unit_type"], "exclusive_area_sqm": r["area_sqm"]} for r in reviewed["sale_prices"]],
                              quote=normal(next(p["text"] for p in pages if p["page"] == 2))[:900], page=2))
            qualification = next(p for p in pages if p["page"] == 4)
            quote = normal(qualification["text"])
            age = re.search(r"분양광고일[^Ÿ]{0,200}만\s*19세\s*이상", quote)
            rules.append(make("age_min", 19, supply="일반공급", operator=">=", unit="years", quote=age.group(0), page=4))
            domestic = [make("residence_region", region_code=code, region_name=name, quote="대한민국에 거주하는 만 19세 이상인 자", page=4) for name, code in PROVINCES.items()]
            rules.append(make("any", supply="일반공급", label="국내 거주", text="대한민국 거주", conditions=domestic, quote="분양광고일 현재 대한민국에 거주하는 만 19세 이상인 자 또는 법인", page=4))
        if nonrank_apt and cutoff:
            original_cutoff, original_evidence = document_cutoff(pages)
            old_context = next((r.get("value", {}) for r in payload.get("rules", []) if r.get("kind") == "qualification_context" and r.get("verification") == "official"), {})
            context = {**old_context, "original_announcement_date": original_cutoff, "application_announcement_date": cutoff, "application_criterion_date": cutoff}
            rules.append(make("qualification_context", context, effect="metadata", quote=cutoff_evidence["text"] + (" / " + original_evidence["text"] if original_evidence else ""), page=cutoff_evidence["page"]))
            parsed = parse_unranked_conditions(pages, method=method, cutoff=cutoff, reviewed=reviewed, make=make)
            rules.extend(parsed["rules"])
            if reviewed and reviewed.get("unranked_inventory"):
                stock = reviewed["unranked_inventory"]
                page = next((p for p in pages if p["page"] == stock["page"]), None)
                if page and all(unit.lstrip("0") in page["text"] for unit in stock["units"]):
                    inventory = [{"unit_type":unit,"supply_type":"일반공급","supply_count":count,
                                  "verification":"official","evidence_url":url,"document_hash":digest,
                                  "criterion_date":cutoff,"evidence_page":stock["page"],
                                  "evidence_text":normal(page["text"])[normal(page["text"]).find("공급대상"):][:800]}
                                 for unit,count in stock["units"].items() if count > 0]
                    rules.append(make("offered_supplies", effect="metadata", supplies=inventory, inventory_status="verified",
                                      quote=inventory[0]["evidence_text"], page=stock["page"]))
            offered = parsed["offered_supply_types"]
            full = parsed["complete"]
            missing = parsed["missing_topics"]
        else:
            full = bool(prices)
            missing = [] if full else ["공고별 신청 자격"]
        if regional["offered"]:
            offered = regional["offered"]
            # The document's actual inventory replaces a default general route.
            rules = [r for r in rules if r.get("kind") not in {"applicant_regions", "offered_supplies"} and (r.get("effect") == "metadata" or not r.get("supply_type") or r["supply_type"] in offered)]
            rules.extend(regional["rules"])
            rules.extend(residual_special_conditions(pages, reviewed=reviewed, offered=offered, make=make))
            # A regional table review certifies only those topics. Admission
            # coverage is completed when its mandatory sections are reviewed.
            missing = list(reviewed.get("remaining_admission_topics", ["공고의 남은 당첨·계약 제한 및 유형별 예외"]))
            full = bool(reviewed.get("admission_sections_reviewed") and not missing and
                        (not reviewed.get("unranked_review") or parsed["complete"]))
        count = sum(r.get("effect") != "metadata" for r in rules)
        rules.append(make("condition_coverage", effect="metadata", status="complete" if full else "partial", offered_supply_types=offered,
                          scopes=[{"supply_type": supply, "complete": full, "verified_rule_count": sum(r.get("effect") != "metadata" and (not r.get("supply_type") or r.get("supply_type") == supply) for r in rules), "missing_topics": missing} for supply in offered], quote=normal(anchor["text"])[:850], page=anchor["page"], completion_basis="document_hash_review" if full and nonrank_apt else "validated_document_parser" if full else None))
        return {"rules": rules, "prices": prices, "offered_supply_types": offered, "offered_supplies":regional["supplies"], "status": "complete" if full else "partial", "parser_version": PARSER_VERSION}

    class_pattern = r"민영주택으로|민영주택\s*입주자모집공고" if kind == "private" else r"「주택법」에\s*의한\s*국민주택"
    classification_quote = next((p for p in pages if re.search(class_pattern, normal(p["text"]))), pages[0])
    class_text = normal(classification_quote["text"])
    class_match = re.search(class_pattern, class_text)
    class_offset = max(0, class_match.start() - 120) if class_match else 0
    if not official_kind or not any(r.get("kind") == "housing_classification" and r.get("verification") == "official" and r.get("source") != "official_document_parser" for r in payload.get("rules", [])):
        rules.append(make("housing_classification", effect="metadata", quote=class_text[class_offset:class_offset + 700], page=classification_quote["page"], source="official_document_parser"))
    old_context = next((r.get("value", {}) for r in payload.get("rules", []) if r.get("kind") == "qualification_context" and r.get("verification") == "official"), {})
    public_context = {**old_context, "original_announcement_date": cutoff,
                      "application_announcement_date": cutoff, "application_criterion_date": cutoff,
                      "application_criterion_basis": "announcement"}
    if "「공공주택특별법」에의한공공주택" in flat:
        public_context["public_housing"] = True
    rules.append(make("qualification_context", effect="metadata", value=public_context,
        quote=cutoff_evidence["text"], page=cutoff_evidence["page"]))

    # Reviewed column layout: a dwelling type expressed as exclusive m² and
    # its separate 주거전용면적 column must agree. SUPLY_AR is never used here.
    for p in pages[:12]:
        table = compact(p["text"])
        if "주택형" not in table or not re.search(r"전용면적기준|주거전용", table):
            continue
        units = []
        source_rows = []
        for m in re.finditer(r"(?<![\d.])(\d{2,3}\.\d{4})([A-Z]?)\s+(?:\d{2,3}[A-Z]?)\s+(\d{2,3}\.\d{4})(?![\d.])", p["text"]):
            if m.group(1) != m.group(3) and float(m.group(1)) != float(m.group(3)):
                continue
            number, fraction = m.group(1).split(".")
            units.append({"unit_type": f"{int(number):03d}.{fraction}{m.group(2)}", "exclusive_area_sqm": float(m.group(3))})
            source_rows.append(normal(m.group(0)))
        if units:
            rules.append(make("unit_exclusive_areas", effect="metadata", units=units, quote=" / ".join(source_rows), page=p["page"]))

    shinhee = "신혼희망타운" in flat[:10000] and kind == "national"
    if not shinhee:
        rules.append(make("application_method", "apt_ranked", effect="metadata", quote=normal(pages[0]["text"])[:700], page=pages[0]["page"]))
    rules.append(make("rank_applicability", effect="metadata", status="not_applicable" if shinhee else "applicable", account_required=True,
                      reason="신혼희망타운 별도 신청자격 적용 · 일반공급 1·2순위 적용 없음" if shinhee else "아파트 일반공급 1·2순위 적용", quote=normal(pages[0]["text"])[:700], page=pages[0]["page"]))
    sections = _sections(pages, shinhee)
    offered = list(dict.fromkeys(s["supply_type"] for s in sections))
    for section in sections:
        supply = section["supply_type"]
        lines = section["lines"]
        joined = normal(" ".join(l["text"] for l in lines))
        # Only the applicant qualification portion; points, priority selection
        # and other types' account tables cannot become eligibility facts.
        qualified = re.split(r"당첨자\s*선정방법|■\s*당첨자\s*선정|배점항목", joined)[0]
        start_page = section["page"]
        def condition_anchor(match: re.Match, *, before: int = 100, after: int = 180) -> dict:
            # The decisive phrase can occur on a later page of the same
            # section. Locate it against normalized line lengths, not the
            # section's start page or a fixed prefix of its text.
            cursor = 0
            page = start_page
            for line in lines:
                line_text = normal(line["text"])
                if not line_text:
                    continue
                length = len(line_text) + 1
                if cursor + length > match.start():
                    page = line["page"]
                    break
                cursor += length
            return {"quote": qualified[max(0, match.start() - before):min(len(qualified), match.end() + after)], "page": page}
        general = supply == "일반공급"
        special_exceptions = not general and ("출산특례" in flat or "혼인특례" in flat)
        homeless = re.search(r"무주택\s*세대(?:구성원|주)", qualified)
        if homeless:
            r = make("homeless", True, supply=supply, **condition_anchor(homeless), unit="boolean")
            if "예비신혼부부" in qualified:
                r = exceptional(r, "예비신혼부부의 혼인으로 구성될 세대 범위 확인", qualified)
            elif special_exceptions:
                r = exceptional(r, "출산특례 등 무주택 요건의 공식 예외 확인", "공고문에 출산특례·혼인특례가 명시되어 있습니다. 해당 유형의 적용 범위와 기존주택 처분 조건을 확인해야 합니다.")
            rules.append(r)
        # Applicant regions are explicitly named in the same qualification
        # sentence. Priority regions are retained separately as priority facts.
        region_match = next(re.finditer(r"입주자모집공고일[^■①②③]{0,260}?거주[^■①②③]{0,110}", qualified), None)
        if region_match:
            region_sentence = region_match.group(0)
            names = _province_scopes(region_sentence)
            if names and not (reviewed and reviewed.get("regions")):
                evidence = condition_anchor(region_match, before=0, after=0)
                children = [make("residence_region", **evidence, region_name=name, region_code=PROVINCES[name]) for name in names]
                r = make("any", supply=supply, **evidence, label="신청 가능한 거주지역", text=" · ".join(names), conditions=children)
                if "장기복무" in flat:
                    r = exceptional(r, "장기복무 군인의 공식 거주 예외 확인", "장기복무 군인의 거주지역 예외는 복무기간·추천 여부·공급유형을 원문에서 확인해야 합니다.")
                rules.append(r)

        if kind == "private":
            month_matches = list(re.finditer(r"(?:청약통장\s*가입기간|청약(?:예금|부금|종합저축)|주택청약종합저축)[^■①②③]{0,100}?(\d+)개월(?:이)?\s*(?:경과|이상)", qualified))
            values = {int(m.group(1)) for m in month_matches}
            if len(values) == 1:
                r = make("private_rank_months", next(iter(values)), supply=None if general else supply, **condition_anchor(month_matches[0]), operator=">=", unit="months", purpose="first_rank" if general else "eligibility")
                if supply == "기관추천 특별공급":
                    r = exceptional(r, "기관추천 중 통장 불필요 대상 여부 확인", "장애인·국가유공자·철거주택 소유자 등 공고에 명시된 통장 예외를 확인해야 합니다.")
                rules.append(r)
            table, anchor = _deposit_table(lines)
            if table:
                r = make("deposit_min_krw", supply=None if general else supply, quote=anchor["text"], page=anchor["page"], unit="KRW", operator=">=", deposit_table=table, purpose="first_rank" if general else "eligibility", require_as_of_date=True, value_basis="announcement_balance", cutoff_note="통장 종류별 예치금 충족일·규모 변경일은 공고 원문을 추가 확인하세요.")
                if supply == "기관추천 특별공급":
                    r = exceptional(r, "기관추천 중 통장 불필요 대상 여부 확인", qualified)
                rules.append(r)
            account_match = re.search(r"청약예금[^■①②③]{0,250}주택청약종합저축|주택청약종합저축[^■①②③]{0,250}청약예금", qualified)
            if general and account_match:
                rules.append(make("account_type", supply=None, **condition_anchor(account_match), purpose="first_rank", allowed_values=["comprehensive", "deposit", "installment"], text="민영주택 청약 가능 통장(청약부금은 전용 85㎡ 이하)", area_limit_for_installment=85))
            if general and reviewed and "household_head" in reviewed.get("rank_required_kinds", []):
                # Reviewed regulated-region rank conditions, not general
                # eligibility or special-supply restrictions.
                head = re.search(r"세대주일\s*것", qualified)
                count = re.search(r"2주택\s*이상을\s*소유한\s*세대에\s*속하지\s*않을\s*것", qualified)
                history = re.search(r"과거\s*5년\s*이내\s*당첨된\s*분의\s*세대에\s*속하지\s*않을\s*것", qualified)
                if head: rules.append(make("household_head", True, purpose="first_rank", **condition_anchor(head)))
                if count: rules.append(make("ownership_count_max", 1, purpose="first_rank", operator="<=", unit="homes", **condition_anchor(count)))
                if history: rules.append(make("previous_winning", False, purpose="first_rank", months=60, **condition_anchor(history)))
        else:
            # National general rank must come from its actual rank table; a
            # special supply's six payments must never leak into general rank.
            rank_lines = lines if general else [{"page": start_page, "text": qualified}]
            for l in rank_lines:
                rank = re.search(r"1순위\s*입주자저축에\s*가입하여\s*(?:(\d+)년\((\d+)개월\)|(\d+)개월|([0-9]+)년)[^\n]{0,120}?(\d+)회\s*이상\s*납입", l["text"]) if general else re.search(r"입주자저축에\s*가입하여\s*(\d+)개월[^■①②③]{0,120}?(\d+)회\s*이상\s*납입", l["text"])
                if not rank:
                    continue
                if general:
                    years, explicit_months, months, only_years, payments = rank.groups()
                    period = int(explicit_months or months or int(years or only_years) * 12)
                    if years and int(years) * 12 != period:
                        continue
                else:
                    period, payments = map(int, rank.groups())
                rules.append(make("national_rank_months", period, supply=None if general else supply, quote=rank.group(0), page=l["page"], purpose="first_rank" if general else "eligibility", operator=">=", unit="months"))
                rules.append(make("recognized_payments_min", int(payments), supply=None if general else supply, quote=rank.group(0), page=l["page"], purpose="first_rank" if general else "eligibility", operator=">=", unit="payments", require_as_of_date=True, value_basis="announcement_payments"))
                if general and reviewed and "account_type" in reviewed.get("rank_required_kinds", []):
                    rules.append(make("account_type", purpose="first_rank", allowed_values=["comprehensive", "savings"], text="국민주택 청약 가능 입주자저축(주택청약종합저축·청약저축)", quote=rank.group(0), page=l["page"]))
                break

        if supply.startswith("다자녀"):
            m = re.search(r"만\s*(\d+)세\s*미만의\s*자녀\s*(\d+)명\s*이상\s*\(([^)]+)\)", qualified)
            if m and "태아" in m.group(3) and "입양" in m.group(3):
                rules.append(make("children_min", int(m.group(2)), supply=supply, quote=m.group(0), page=start_page, child_age_max=int(m.group(1)), child_age_inclusive=False, include_pregnancy=True, include_adoption=True, operator=">=", unit="children"))
        if supply.startswith("신혼부부"):
            m = re.search(r"혼인기간(?:이)?\s*(\d+)년\s*이내", qualified)
            if m:
                marriage = make("marriage_months_max", int(m.group(1)) * 12, quote=m.group(0), page=start_page, operator="<=", unit="months", anniversary_limit=True)
                if "재혼" in qualified:
                    marriage = exceptional(marriage, "동일 배우자와 재혼한 경우 전체 혼인기간 합산 확인", "동일 배우자와 재혼한 경우 이전 혼인기간을 합산하는 공고의 요구가 있습니다.")
                child_alternative = kind == "national" and re.search(r"(?:또는|이거나)\s*6세\s*이하", qualified) and "만7세미만" in compact(qualified)
                if child_alternative:
                    child = make("children_min", 1, quote=qualified[:700], page=start_page, child_age_max=7, child_age_inclusive=False, include_pregnancy=True, include_adoption=True, operator=">=")
                    married = make("marital_status", quote=qualified[:700], page=start_page, allowed_values=["married"])
                    normal_branch = make("all", quote=qualified[:700], page=start_page, label="혼인 중인 신혼부부", conditions=[married, make("any", quote=qualified[:700], page=start_page, label="혼인·자녀 요건", text="혼인 7년 이내 또는 만 7세 미만 자녀(태아 포함)", conditions=[marriage, child])])
                    if "예비신혼부부" in qualified or "한부모가족" in qualified:
                        alternative = make("unparsed", quote=qualified[:850], page=start_page, label="예비신혼부부·한부모가족의 별도 신청요건", text="예비신혼부부는 입주 전 혼인 증명과 예정 세대, 한부모가족은 법정 자격 및 자녀 기준을 확인해야 합니다.")
                        rules.append(make("any", supply=supply, quote=qualified[:850], page=start_page, label="신혼부부 특별공급의 신청 가족 유형", conditions=[normal_branch, alternative]))
                    else:
                        normal_branch["supply_type"] = supply
                        rules.append(normal_branch)
                else:
                    marriage["supply_type"] = supply
                    rules.append(marriage)
                    rules.append(make("marital_status", supply=supply, quote=m.group(0), page=start_page, allowed_values=["married"]))
        if supply.startswith("노부모"):
            m = re.search(r"(?:만\s*)?(\d+)세\s*이상의\s*직계존속[^■]{0,120}?(\d+)년\s*이상\s*계속하여\s*부양", qualified)
            if m:
                rules.append(make("parent_age_min", int(m.group(1)), supply=supply, quote=m.group(0), page=start_page, operator=">=", unit="years"))
                rules.append(make("parent_support_months_min", int(m.group(2)) * 12, supply=supply, quote=m.group(0), page=start_page, operator=">=", unit="months"))
                registration = qualified[m.start():m.end() + 180]
                if re.search(r"같은\s*세대별\s*주민등록표등본", registration):
                    rules.append(make("parent_same_register", True, supply=supply, quote=registration, page=start_page))
            head = re.search(r"무주택세대주|무주택세대구성원\s*중\s*세대주", qualified)
            if head:
                rules.append(make("household_head", True, supply=supply, **condition_anchor(head)))
        if supply.startswith("생애최초"):
            owned = re.search(r"세대구성원[^■]{0,180}?과거[^■]{0,120}?주택[^■]{0,90}?소유", qualified)
            if owned:
                r = make("never_owned_home", True, supply=supply, **condition_anchor(owned))
                if "혼인신고" in qualified or "혼인신고" in flat:
                    r = exceptional(r, "배우자 혼인 전 주택 소유·처분의 공식 예외 확인", qualified)
                rules.append(r)
            m = re.search(r"(\d+)년\s*이상\s*소득세", qualified)
            if m:
                r = make("tax_years_min", int(m.group(1)), supply=supply, **condition_anchor(m), operator=">=", unit="years")
                if "세액공제" in qualified or "납부의무" in compact(qualified):
                    r = exceptional(r, "소득세 납부의무·소득공제·세액공제 인정 연수 확인", qualified)
                rules.append(r)
        if supply.startswith("신생아"):
            m = re.search(r"2세\s*미만[^■]{0,120}?자녀(?:\s*\([^)]*\))?", qualified)
            if m:
                rules.append(make("newborn_children_min", 1, supply=supply, quote=m.group(0), page=start_page, child_months_max=24, child_age_inclusive="2세가되는날을포함" in compact(qualified), include_pregnancy=bool(re.search(r"태아|임신", qualified)), include_adoption="입양" in qualified, operator=">=", unit="children"))

    # Exact document reviews supplement conditions whose table layout needs a
    # human comparison. Hash/URL and the parsed source page must all match.
    if reviewed:
        source_pages = {p["page"]: p for p in pages}
        if reviewed.get("regional_review") and kind == "private" and reviewed.get("rank_required_kinds"):
            rank_pages = [p for p in pages if p["page"] in reviewed.get("rank_reviewed_pages", [])]
            rank_lines = [{"page":p["page"],"text":line} for p in rank_pages for line in p["text"].splitlines()]
            table, table_source = _deposit_table(rank_lines)
            period = next((p for p in rank_pages if re.search(r"가입하여\s*6개월", normal(p["text"]))), None)
            present = {r["kind"] for r in rules if r.get("purpose") == "first_rank"}
            if period and "private_rank_months" not in present:
                rules.append(make("private_rank_months",6,purpose="first_rank",operator=">=",unit="months",quote=normal(period["text"])[:800],page=period["page"]))
            if table and "deposit_min_krw" not in present:
                rules.append(make("deposit_min_krw",purpose="first_rank",deposit_table=table,require_as_of_date=True,value_basis="announcement_balance",quote=table_source["text"],page=table_source["page"]))
        if reviewed.get("regions") and not reviewed.get("regional_review") and reviewed.get("region_page") in source_pages:
            region_page = reviewed["region_page"]
            body = normal(source_pages[region_page]["text"])
            match = re.search(r"(?:입주자모집공고일|최초입주자모집공고일)\s*현재[^■]{0,420}?거주[^■]{0,300}?청약(?:이|\s*신청)?(?:\s*가능|할)", body)
            if not match:
                match = re.search(r"입주자모집공고일\s*현재[^■]{0,400}?거주하는[^■]{0,200}", body)
            if match:
                fields = {"regions": reviewed["regions"], "local_priority": {**reviewed["local_priority"], "criterion_date": cutoff}, "scope_complete": True}
                if reviewed.get("military_exception"):
                    military = re.search(r"10년\s*이상\s*장기복무[^■]{0,420}", body)
                    if military:
                        fields["exceptions"] = [make("military_service_years", effect="metadata", quote=military.group(0), page=region_page,
                                                    **{k: v for k, v in reviewed["military_exception"].items() if k != "kind"})]
                rules.append(make("applicant_regions", effect="metadata", quote=match.group(0), page=region_page, **fields))
        if reviewed.get("allocation_method") and reviewed.get("allocation_page") in source_pages:
            allocation_page = reviewed["allocation_page"]
            body = normal(source_pages[allocation_page]["text"])
            match = re.search(r"①지역\s*:\s*해당지역\s*거주자[^■]{0,400}?기타지역\s*거주자[^■]{0,300}", body)
            if match:
                rules.append(make("regional_allocation", effect="metadata", supply="일반공급", allocation_method=reviewed["allocation_method"], local_share_percent=100,
                                  local_region={**reviewed["local_priority"], "criterion_date": cutoff}, quote=match.group(0), page=allocation_page))
        required = reviewed.get("rank_required_kinds", [])
        first_rules = [r for r in rules if r.get("purpose") == "first_rank"]
        first_kinds = {r["kind"] for r in first_rules}
        reviewed_pages = reviewed.get("rank_reviewed_pages", [])
        if required and set(required) <= first_kinds and all(p in source_pages for p in reviewed_pages):
            rules.append(make("rank_requirements", effect="metadata", complete=True, required_kinds=required,
                              quote=" / ".join(r["evidence_text"] for r in first_rules), page=reviewed_pages[-1], reviewed_pages=reviewed_pages,
                              completion_basis="document_hash_review", scope="first_rank", supply="일반공급"))

    if not shinhee and not any(r["kind"] == "rank_requirements" for r in rules):
        first_rules = [r for r in rules if r.get("purpose") == "first_rank"]
        required = ["account_type", "private_rank_months", "deposit_min_krw"] if kind == "private" else ["account_type", "national_rank_months", "recognized_payments_min"]
        kinds = {r["kind"] for r in first_rules}
        nonregulated = bool(re.search(r"비투기과열지구\s*및\s*비청약과열지역", text)) or (old_context.get("speculation_zone") is False and old_context.get("subscription_overheated") is False)
        # The tested ordinary private template has all account, duration and
        # deposit requirements plus explicitly nonregulated context. A mere
        # collection of keywords cannot certify a regulated/ambiguous table.
        if kind == "private" and nonregulated and set(required) <= kinds and all(not r.get("exceptions") for r in first_rules):
            rules.append(make("rank_requirements", effect="metadata", complete=True, required_kinds=required, scope="first_rank", supply="일반공급",
                              completion_basis="validated_nonregulated_rank_table", quote=" / ".join(r["evidence_text"] for r in first_rules), page=first_rules[0]["evidence_page"]))

    if regional["offered"]:
        offered = regional["offered"]
        rules = [r for r in rules if r.get("effect") == "metadata" or not r.get("supply_type") or r["supply_type"] in offered]
        rules.extend(regional["rules"])
    elif not shinhee:
        from .supply_inventory import official_supplies
        inventory, inventory_status = official_supplies(pages,payload,make=make)
        if inventory:
            offered=list(dict.fromkeys(r["supply_type"] for r in inventory))
            rules.append(make("offered_supplies",effect="metadata",supplies=inventory,inventory_status=inventory_status,quote=inventory[0].get("evidence_text"),page=inventory[0].get("evidence_page")))
            rules=[r for r in rules if r.get("effect")=="metadata" or not r.get("supply_type") or r["supply_type"] in offered]

    from .shinhee_rules import a17_conditions
    a17 = a17_conditions(pages,digest=digest,make=make)
    if a17:
        offered=a17["offered"]
        rules=[r for r in rules if r.get("effect")=="metadata" and r.get("kind") not in {"rank_applicability","applicant_regions","offered_supplies"}]
        rules.extend(a17["rules"])

    # Remove duplicate tables/headings across pages without removing corrected
    # semantics. Scope completeness is never inferred from the count of facts.
    unique: dict[str, dict] = {}
    for rule in rules:
        identity = json.dumps({k: v for k, v in rule.items() if k not in {"id", "evidence_text", "evidence_page"}}, ensure_ascii=False, sort_keys=True)
        unique.setdefault(identity, rule)
    rules = list(unique.values())
    counts = Counter(r.get("supply_type", "일반공급") for r in rules if r.get("effect") != "metadata")
    scopes = []
    for supply in offered:
        conditions = [r for r in rules if r.get("effect") != "metadata" and r.get("purpose") != "first_rank" and (not r.get("supply_type") or r["supply_type"] == supply)]
        remaining = (reviewed or {}).get("remaining_topics_by_supply", {}).get(supply, ["재당첨·청약 제한 및 법령 예외", "예정 세대·동일 배우자 재혼 이력 및 사전청약 별도 경로" if a17 else "소득·자산 분기" if supply != "일반공급" or kind == "national" else "신청 제한·연령 예외의 전체 검토"])
        topics = [{"topic":r.get("label") or r["kind"],"status":"partial" if r["kind"] == "unparsed" else "verified","required":True,"rule_ids":[r["id"]]} for r in conditions]
        topics.extend({"topic":topic,"status":"missing","required":True,"rule_ids":[]} for topic in remaining)
        complete = bool(conditions and all(t["status"] == "verified" for t in topics))
        scopes.append({"supply_type":supply,"complete":complete,"verified_rule_count":len(conditions),"topics":topics,"missing_topics":remaining})
    coverage_status = "complete" if scopes and all(s["complete"] for s in scopes) else "partial" if counts else "unsupported"
    rules.append(make("condition_coverage", effect="metadata", quote=cutoff_evidence["text"], page=cutoff_evidence["page"], status=coverage_status, offered_supply_types=offered, scopes=scopes, covered_supply_types=[s for s in offered if counts[s]], source="official_document_parser"))
    return {"rules": rules, "offered_supply_types": offered, "status": coverage_status, "parser_version": PARSER_VERSION}
