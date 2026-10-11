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

from .unranked_rules import parse_unranked_conditions

PARSER_VERSION = "official-sections-2026-10-11-v15"
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
    # Later reviewed geography/admission supplements add source-bound facts.
    # Prior valid facts remain available until their document is reparsed.
    if rule.get("parser_version") in {"official-sections-2026-10-05-v5", "official-sections-2026-10-05-v6", "official-sections-2026-10-05-v7", "official-sections-2026-10-07-v8", "official-sections-2026-10-07-v9", "official-sections-2026-10-09-v10", "official-sections-2026-10-09-v11", "official-sections-2026-10-09-v12", "official-sections-2026-10-09-v13"}:
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
        ("unranked_after", r"무순위\s*\(?\s*사후\s*\)?\s*(?:\(\s*\d+차\s*\)\s*)?입주자\s*모집공고"),
        ("optional_supply", r"임의\s*공급\s*(?:입주자)?\s*모집공고"),
        ("first_come", r"(?:선착순\s*(?:동[·ㆍ]?호\s*지정|계약|일반매각)|\(선착순)"),
    )
    for page in pages:
        lines = page["text"].splitlines()
        for index, line in enumerate(lines):
            # The applicant offer is identified by a document title, wherever
            # it occurs. Later prose about leftover contracts is not a title.
            heading = normal(" ".join(lines[index:index + 3]))
            if not re.search(r"(?:입주자\s*)?모집공고|오피스텔\s*분양(?:광고|공고)", heading):
                continue
            if re.match(r"[■•※▌]|(?:\d+[-.]?\s+)?(?:유의사항|계약조건)", heading):
                continue
            for value, pattern in patterns:
                found = re.search(pattern, heading)
                if found and (value != "first_come" or re.search(r"(?:입주자\s*)?모집공고|매각\s*공고", heading)):
                    return value, {"page": page["page"], "text": found.group(0)}
    return "unknown", None


def document_cutoff(pages: list[dict], *, method: str = "unknown") -> tuple[str | None, dict | None]:
    """Only an explicit statement of the qualification announcement cutoff."""
    if method in {"unranked_after", "optional_supply", "cancelled_resupply"}:
        method_name = r"무순위\s*\(?사후\)?" if method == "unranked_after" else r"임의\s*공급" if method == "optional_supply" else r"(?:불법행위\s*재공급|계약\s*취소(?:\s*주택)?\s*재공급)"
        current = re.compile(r"(?:본\s*(?:주택의\s*)?)?" + method_name + r"\s*입주자\s*모집공고일[은는]\s*(?:\([^)]{0,3}\)\s*)?(20\d{2})[.년\-/]\s*(\d{1,2})[.월\-/]\s*(\d{1,2})")
        for page in pages:
            match = current.search(normal(page["text"]))
            if match:
                try:
                    return date(*(int(v) for v in match.groups())).isoformat(), {"page": page["page"], "text": match.group(0)}
                except ValueError:
                    pass
        # The schedule table may put the labels before the dates, with PDF
        # extraction moving weekday labels ahead of the date columns.
        for page in pages:
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
    # A divided offering may have PDF numeric tokens moved within the same
    # explicit criterion bullet. Use that bullet's one date, not a cover date.
    for page in pages:
        text = normal(page["text"])
        statement = re.search(r"본\s*주택의\s*(?:\d+\s*회차|회차)\s*입주자모집공고일은[^■▌]{0,400}", text)
        if statement:
            values = set()
            for values_raw in re.findall(r"(20\d{2})[.년\-/]\s*(\d{1,2})[.월\-/]\s*(\d{1,2})", statement[0]):
                try:
                    values.add(date(*(int(v) for v in values_raw)).isoformat())
                except ValueError:
                    pass
            if len(values) == 1:
                return values.pop(), {"page": page["page"], "text": statement[0]}
    for page in pages:
        text = normal(page["text"])
        match = re.search(r"(?:(?:이\s*주택의|본\s*주택의)\s*(?:최초\s*)?입주자모집공고일[은는]\s*|(?:분양|모집)광고일[‘’'“”\s]*\()(20\d{2})[.년\-/]\s*(\d{1,2})[.월\-/]\s*(\d{1,2})", text)
        if match:
            try:
                cutoff = date(*(int(v) for v in match.groups())).isoformat()
                return cutoff, {"page": page["page"], "text": match.group(0)}
            except ValueError:
                continue
    # A closed official schedule explicitly names the announcement-date
    # column first. Numeric/weekday reordering within later columns does not
    # change the first printed date belonging to this column.
    for page in pages:
        lines = page["text"].splitlines()
        for index, line in enumerate(lines):
            if not re.match(r"\s*구\s*분\s+입주자모집공고일\s+", line):
                continue
            following = normal(" ".join(lines[index + 1:index + 5]))
            row = re.match(r"일\s*정\s*(20\d{2})[.년\-/]\s*(\d{1,2})[.월\-/]\s*(\d{1,2})", following)
            if row:
                try:
                    value = date(*(int(v) for v in row.groups())).isoformat()
                    return value, {"page": page["page"], "text": normal(line) + " / " + row[0]}
                except ValueError:
                    pass
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
    from .generic_admission import _deposit_values
    grouped = {}
    for line in lines:
        grouped.setdefault(line["page"], []).append(line["text"])
    rows, anchor = _deposit_values([{"page": page, "text": "\n".join(body)} for page, body in grouped.items()])
    return (rows, {"page": anchor["page"], "text": anchor["quote"]}) if rows else ([], None)


def _document_area_facts(pages, make):
    """The model code and printed exclusive column must agree in a supply table.

    PDF columns can split '(전용면적기준)' around unrelated header cells. The
    two independent numeric cells and their area subtotal establish the row;
    an advertised supply area or a statute's area limit cannot establish it.
    """
    candidates = []
    for page in pages:
        header = compact(page["text"])
        if not all(label in header for label in ("주택형", "주택공급면적", "전용면적", "공용면적")):
            continue
        units, evidence = [], []
        pattern = r"(?<![\d.])(\d{2,3}\.\d{4})([A-Z]?)\s+(\d{2,3}[A-Z]?)\s+(\d{2,3}\.\d{4})\s+(\d+\.\d+)\s+(\d+\.\d+)"
        for match in re.finditer(pattern, page["text"]):
            model, suffix, alias, exclusive, common, subtotal = match.groups()
            if float(model) != float(exclusive) or alias != str(int(float(model))) + suffix:
                continue
            if abs(float(exclusive) + float(common) - float(subtotal)) > .0002:
                continue
            whole, fraction = model.split(".")
            units.append({"unit_type": f"{int(whole):03d}.{fraction}{suffix}", "exclusive_area_sqm": float(exclusive)})
            evidence.append(normal(match[0]))
        if units:
            candidates.append((page["page"], units, evidence))
    values = {}
    for _, units, _ in candidates:
        for unit in units:
            previous = values.setdefault(unit["unit_type"], unit["exclusive_area_sqm"])
            if previous != unit["exclusive_area_sqm"]:
                return []
    return [make("unit_exclusive_areas", effect="metadata", units=units,
                 quote=" / ".join(evidence), page=page) for page, units, evidence in candidates]


def _document_cap_fact(pages, make):
    # A direct declaration about this offering outranks statutory example
    # tables that also mention price-capped homes with different restrictions.
    candidates = []
    for page in pages:
        body = normal(page["text"])
        for match in re.finditer(r"본\s*(?:주택|아파트)[^■•。.]{0,250}?분양가\s*상한제(?:가)?\s*(미적용|비적용|적용되지\s*않는|적용(?:되는)?)\s*(?:민영주택|주택|아파트)(?:으로|이며|입니다|에\s*해당)", body):
            candidates.append(("yes" if match[1].startswith("적용") and "않" not in match[1] else "no", page["page"], match[0]))
    if not candidates or len({value for value, _, _ in candidates}) != 1:
        return []
    value, page, quote = candidates[0]
    return [make("price_cap", value, effect="metadata", quote=quote, page=page)]


def parse_official_rules(pages: list[dict], *, url: str, digest: str, payload: dict | None = None) -> dict:
    # A known hash for another notice cannot validate the requested notice.
    source_query = parse_qs(urlparse(str((payload or {}).get("official_url", ""))).query)
    attachment_query = parse_qs(urlparse(url).query)
    expected_id = (source_query.get("houseManageNo") or [None])[0]
    attachment_id = (attachment_query.get("houseManageNo") or [None])[0]
    publication_id = (attachment_query.get("pblancNo") or [None])[0]
    if attachment_id and (expected_id and attachment_id != expected_id or publication_id and publication_id != attachment_id):
        return {"rules": [], "offered_supply_types": [], "status": "unsupported",
                "identity_status": "mismatch", "reason": "현재 공고번호와 첨부 문서의 공고번호가 일치하지 않습니다."}
    from .contract_schedule import parse_contract_schedule
    result = _parse_official_rules(pages, url=url, digest=digest, payload=payload)
    # A source rejected for this notice's identity must not acquire verified
    # schedules, regional scopes or selection facts from its unrelated bytes.
    if result.get("identity_status") == "mismatch":
        return result
    contract = parse_contract_schedule(pages, url=url, digest=digest, parser_version=PARSER_VERSION)
    if contract:
        context_rule = next((r for r in result.get("rules", []) if "criterion_date" in r), None)
        contract["criterion_date"] = context_rule.get("criterion_date") if context_rule else None
        contract["criterion_basis"] = context_rule.get("criterion_basis") if context_rule else None
        result["rules"] = [r for r in result.get("rules", []) if r.get("kind") != "contract_schedule"] + [contract]
        result["contract_schedule"] = {k: contract.get(k) for k in (
            "status", "start_date", "end_date", "verification", "source", "evidence_url", "evidence_text", "evidence_page", "document_hash")}
    from .selection_rules import parse_selection_rules
    from .application_regions import explicit_applicant_regions
    cutoff = next((r.get("criterion_date") for r in result.get("rules", []) if r.get("criterion_date")), None)
    if cutoff:
        def regional_make(kind, *, quote, page, **fields):
            identity = json.dumps([digest, kind, quote, fields], ensure_ascii=False, sort_keys=True)
            regional_fact = {"id": "official-" + hashlib.sha256(identity.encode()).hexdigest()[:16],
                "kind": kind, "verification": "official", "source": "official_document_parser",
                "parser_version": PARSER_VERSION, "document_hash": digest, "evidence_url": url,
                "evidence_text": quote, "evidence_page": page, "criterion_date": cutoff,
                "criterion_basis": "announcement", **fields}
            housing_kind = next((r.get("housing_kind") for r in result.get("rules", []) if r.get("housing_kind")), None)
            if housing_kind:
                regional_fact["housing_kind"] = housing_kind
            if any(p.get("page") == page and p.get("source_format") == "hwpx_section" for p in pages):
                regional_fact["evidence_section"] = page
                regional_fact["evidence_page"] = None
            return regional_fact
        method = next((r.get("value") for r in result.get("rules", []) if r.get("kind") == "application_method"), None)
        regions = explicit_applicant_regions(pages, cutoff=cutoff, make=regional_make, provinces=PROVINCES, method=method)
        if regions:
            # An earlier subtype paragraph or a bank exemption can mention a
            # province without describing the common applicant geography.
            # Resolve that geography independently from the operative source.
            result["rules"] = [r for r in result.get("rules", []) if not
                (r.get("kind") == "applicant_regions" and not r.get("supply_type"))]
            result["rules"].extend(regions)
            if result.get("status") == "unsupported":
                result["status"] = "partial"
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
    if cutoff is None and (payload.get("category") == "officetel" or method == "officetel"):
        from .generic_admission import office_qualification
        qualification = office_qualification(pages)
        if qualification:
            cutoff, cutoff_evidence = qualification["date"], {"page": qualification["page"], "text": qualification["quote"]}
    # A correction may have a new publication date. Only the explicitly stated
    # original cutoff is used, and conflicting source context blocks parsing.
    original = next((r.get("value", {}).get("original_announcement_date") for r in payload.get("rules", []) if r.get("kind") == "qualification_context"), None)
    nonrank_apt = method in {"unranked_after", "optional_supply", "cancelled_resupply"}
    previous_application = next((r.get("value", {}).get("application_criterion_date") for r in payload.get("rules", []) if r.get("kind") == "qualification_context"), None)
    expected_cutoff = previous_application or payload.get("announcement_date") if nonrank_apt else original or payload.get("announcement_date")
    context_conflict = bool(expected_cutoff and cutoff and str(expected_cutoff)[:10] != cutoff)
    manage_no = (parse_qs(urlparse(str(payload.get("official_url", ""))).query).get("houseManageNo") or [None])[0]
    # An exact current attachment URL carries the notice identifier even
    # when the PDF does not print it. Qualification date is checked separately.
    attachment_manage_no = (parse_qs(urlparse(url).query).get("houseManageNo") or [None])[0]
    if manage_no and manage_no not in flat and attachment_manage_no != manage_no:
        title_key = compact(re.sub(r"\((?:조합원\s*취소분|\d+회차)\)", "", str(payload.get("title", "")))).replace("&", "앤").replace("Ⅱ", "II")
        header_key = flat.replace("&", "앤").replace("Ⅱ", "II")
        if not title_key or title_key not in header_key:
            context_conflict = True
    official_kind = next((r.get("housing_kind") for r in payload.get("rules", []) if r.get("kind") == "housing_classification" and r.get("verification") == "official"), None)
    private = bool(re.search(r"민영주택으로|민영주택입주자모집공고", flat)) or bool(re.search(r"주택유형[^■]{0,100}민영|주택구분[^■]{0,300}민영", flat))
    national = bool(re.search(r"「주택법」에의한국민주택|주택유형국민|국민주택입주자모집공고", flat))
    kind = "private" if private and not national else "national" if national and not private else official_kind if official_kind in ("private", "national") else "unknown"
    office = payload.get("category") in {"officetel", "living_accommodation"} or bool(re.search(r"오피스텔(?:분양광고|분양공고)", flat)) or ("오피스텔" in str(payload.get("title", "")) and "오피스텔" in flat)
    outside_apt = office and (bool(re.search(r"본오피스텔|본생활숙박시설", flat)) or "오피스텔" in flat)
    first_come = method == "first_come"
    unranked = nonrank_apt or payload.get("category") in {"unsold", "optional_supply"}
    if outside_apt:
        kind = "not_applicable"
    classified = kind != "unknown" and not (official_kind and official_kind != kind)
    rules: list[dict] = []
    if context_conflict or (not cutoff and not (first_come or unranked)) or ("입주자모집공고" not in flat and not outside_apt and not first_come) or (not classified and not outside_apt and not first_come and not unranked):
        return {"rules": [], "offered_supply_types": [], "status": "unsupported", "reason": "공식 주택 구분·기준일 또는 문서 맥락을 확인하지 못했습니다.",
                **({"identity_status": "mismatch"} if context_conflict else {})}

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

    regional = {"rules": [], "offered": [], "supplies": []}
    rules.extend(_document_area_facts(pages, make))
    rules.extend(_document_cap_fact(pages, make))

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
            class_source = next((p for p in pages if re.search(r"민영주택|주택유형.{0,150}민영|주택구분.{0,150}민영|국민주택|오피스텔(?:\s*분양광고|\s*분양공고)", normal(p["text"]))), None)
            if class_source:
                rules.append(make("housing_classification", effect="metadata", quote=normal(class_source["text"])[:700], page=class_source["page"]))
        prices = []
        offered = ["일반공급"]
        office_admission = None
        if outside_apt:
            from .generic_admission import generic_office_admission
            office_admission = generic_office_admission(pages, make=make, cutoff=cutoff)
            rules.extend(office_admission["rules"])
            from .office_price_tables import office_price_tables
            prices, price_facts = office_price_tables(pages, make=make)
            rules.extend(price_facts)
        if nonrank_apt and cutoff:
            original_cutoff, original_evidence = document_cutoff(pages)
            old_context = next((r.get("value", {}) for r in payload.get("rules", []) if r.get("kind") == "qualification_context" and r.get("verification") == "official"), {})
            context = {**old_context, "original_announcement_date": original_cutoff, "application_announcement_date": cutoff, "application_criterion_date": cutoff}
            rules.append(make("qualification_context", context, effect="metadata", quote=cutoff_evidence["text"] + (" / " + original_evidence["text"] if original_evidence else ""), page=cutoff_evidence["page"]))
            parsed = parse_unranked_conditions(pages, method=method, cutoff=cutoff, reviewed=None, make=make)
            rules.extend(parsed["rules"])
            offered = parsed["offered_supply_types"]
            full = parsed["complete"]
            missing = parsed["missing_topics"]
        else:
            full = bool(office_admission and office_admission["complete"])
            missing = office_admission["missing_topics"] if office_admission else ["공고별 신청 자격"]
        inventory, inventory_status = [], "unknown"
        special_review = None
        if not outside_apt:
            from .supply_inventory import official_supplies
            inventory, inventory_status = official_supplies(pages, payload, make=make)
            if inventory:
                offered = list(dict.fromkeys(row["supply_type"] for row in inventory))
                rules = [r for r in rules if r["kind"] != "offered_supplies"]
                rules.append(make("offered_supplies", effect="metadata", supplies=inventory, inventory_status=inventory_status,
                                  quote=inventory[0].get("evidence_text") or "", page=inventory[0].get("evidence_page")))
            if nonrank_apt and cutoff and any(supply != "일반공급" for supply in offered):
                from .unranked_rules import parse_nonranked_special_conditions
                special_review = parse_nonranked_special_conditions(pages, offered, make)
                rules.extend(special_review["rules"])
            # The general applicant section is not an offered route in a
            # special-only cancellation supply. Its subtype facts cannot be
            # imposed on another inventory route.
            rules = [r for r in rules if r.get("effect") == "metadata" or not r.get("supply_type") or r["supply_type"] in offered]
        scopes = []
        for supply in offered:
            # The nonranked natural-person review certifies its actual general
            # route. Other source inventory routes require their own clauses.
            supported = outside_apt or supply in (parsed["offered_supply_types"] if nonrank_apt and cutoff else ["일반공급"])
            source_missing = list(missing) if supported else ["이 공급유형의 현재 신청자격·면제 문단 검토"]
            if special_review and supply != "일반공급":
                supported = True
                source_missing = list(special_review["missing_topics"].get(supply, source_missing))
            if inventory_status in {"partial", "conflict"}:
                source_missing.append("모집표의 공급유형·주택형별 물량 대조")
            complete = bool(full and supported and not source_missing)
            review = office_admission if office_admission else parsed if nonrank_apt and cutoff else None
            review_pages = review.get("reviewed_pages") if review else None
            if special_review and supply != "일반공급":
                review = special_review
                review_pages = special_review["reviewed_pages"].get(supply, [])
            scopes.append({"supply_type": supply, "complete": complete,
                           "verified_rule_count": sum(r.get("effect") != "metadata" and (not r.get("supply_type") or r.get("supply_type") == supply) for r in rules),
                           "missing_topics": source_missing,
                           **({"review_version": review["review_version"], "reviewed_pages": review_pages, "completion_basis": "document_structure_reviewed_standard_branch"} if review and review.get("review_version") else {})})
        full = bool(scopes and all(scope["complete"] for scope in scopes))
        rules.append(make("condition_coverage", effect="metadata", status="complete" if full else "partial", offered_supply_types=offered,
                          scopes=scopes, quote=normal(anchor["text"])[:850], page=anchor["page"], completion_basis="document_structure_reviewed_standard_branch" if full else None))

        return {"rules": rules, "prices": prices, "offered_supply_types": offered, "offered_supplies": inventory, "status": "complete" if full else "partial", "parser_version": PARSER_VERSION}

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

    shinhee = "신혼희망타운" in flat and kind == "national"
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
            if names:
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
            account_match = re.search(r"1순위[^■]{0,1600}?(?=-?\s*2순위)", qualified)
            if general and account_match:
                from .generic_admission import _account_types, _unique_int
                allowed = _account_types(account_match[0])
                area = _unique_int(r"전용면적\s*(\d+)㎡\s*이하\s*주택형에\s*한함", account_match[0])
                if allowed and ("installment" not in allowed or area is not None):
                    fields = {"area_limit_for_installment": area} if "installment" in allowed else {}
                    rules.append(make("account_type", supply=None, **condition_anchor(account_match), purpose="first_rank", allowed_values=allowed, **fields))
            if general:
                # Printed regulated-region rank conditions, not general
                # eligibility or special-supply restrictions.
                head = re.search(r"세대주일\s*것", qualified)
                count = re.search(r"(\d+)주택\s*이상을\s*소유한\s*세대에\s*속하지\s*않을\s*것", qualified)
                history = re.search(r"과거\s*(\d+)년\s*이내\s*당첨된\s*분의\s*세대에\s*속하지\s*않을\s*것", qualified)
                if head: rules.append(make("household_head", True, purpose="first_rank", **condition_anchor(head)))
                if count: rules.append(make("ownership_count_max", int(count[1]) - 1, purpose="first_rank", operator="<=", unit="homes", **condition_anchor(count)))
                if history: rules.append(make("previous_winning", False, purpose="first_rank", months=int(history[1]) * 12, **condition_anchor(history)))
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
                if general:
                    rules.append(make("account_type", purpose="first_rank", allowed_values=["comprehensive", "savings"], text="국민주택 청약 가능 입주자저축(주택청약종합저축·청약저축)", quote=rank.group(0), page=l["page"]))
                break

        if supply.startswith("다자녀"):
            m = re.search(r"만\s*(\d+)세\s*미만의\s*자녀\s*(\d+)명\s*이상\s*\(([^)]+)\)", qualified)
            if m and "태아" in m.group(3) and "입양" in m.group(3):
                rules.append(make("children_min", int(m.group(2)), supply=supply, quote=m.group(0), page=start_page, child_age_max=int(m.group(1)), child_age_inclusive=False, include_pregnancy=True, include_adoption=True, operator=">=", unit="children"))
        if supply.startswith("신혼부부"):
            m = re.search(r"혼인기간(?:\([^■]{0,700}?\))?(?:이)?\s*(\d+)년\s*이내", qualified)
            if m:
                marriage = make("marriage_months_max", int(m.group(1)) * 12, **condition_anchor(m), operator="<=", unit="months", anniversary_limit=True)
                if "재혼" in qualified:
                    # A previous multi-child scoring table may mention
                    # remarriage first. Only this applicant section supplies
                    # the marriage-duration condition and its tightening.
                    remarriage = re.search(r"동일인과의\s*재혼.{0,120}?이전\s*혼인기간을\s*포함", qualified)
                    if remarriage:
                        marriage["exceptions"] = [make("unparsed", label="동일 배우자와 재혼한 경우 전체 혼인기간 합산 확인",
                            text="동일 배우자와 재혼한 경우 이전 혼인기간을 합산해야 합니다.", **condition_anchor(remarriage, before=0, after=0))]
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
                spouse_exception = re.search(r"청약신청자의\s*배우자가\s*혼인\s*전\s*주택을\s*소유하였다가\s*혼인\s*전\s*처분한\s*이력은\s*배제합니다", qualified)
                if spouse_exception:
                    r["exceptions"] = [make("unparsed", supply=supply, label="배우자 혼인 전 주택 소유·처분의 공식 예외 확인",
                        text="배우자가 혼인 전에 소유하고 혼인 전에 처분한 주택 이력은 배제합니다.",
                        **condition_anchor(spouse_exception, before=0, after=0))]
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

    if kind == "national" and not shinhee and any(r.get("purpose") == "first_rank" for r in rules):
        # The printed names are a common admission account definition used by
        # this offer, not an account allowlist inferred from a notice identity.
        for page in pages:
            account = re.search(r"주택청약종합저축\s*(?:및|[·ㆍ])\s*청약저축", normal(page["text"]))
            if account:
                rules.append(make("account_type", purpose="first_rank", allowed_values=["comprehensive", "savings"], quote=account[0], page=page["page"]))
                break
    if not shinhee and not any(r["kind"] == "rank_requirements" for r in rules):
        first_rules = [r for r in rules if r.get("purpose") == "first_rank"]
        required = ["account_type", "private_rank_months", "deposit_min_krw"] if kind == "private" else ["account_type", "national_rank_months", "recognized_payments_min"]
        kinds = {r["kind"] for r in first_rules}
        declarations = []
        for page in pages:
            normalized = normal(page["text"])
            header = re.search(r"주택유형.{0,450}?규제지역여부.{0,700}?(?=재당첨제한)", normalized)
            if header:
                declarations.append(header[0])
        nonregulated = bool(re.search(r"비투기과열지구\s*및\s*비청약과열지역", text)) or any("비규제지역" in declaration for declaration in declarations) or (old_context.get("speculation_zone") is False and old_context.get("subscription_overheated") is False)
        regulated = any(re.search(r"(?<!비)투기과열지구|(?<!비)청약과열지역", declaration) for declaration in declarations)
        if kind == "private" and regulated and not nonregulated:
            required.extend(["household_head", "ownership_count_max", "previous_winning"])
        context_known = nonregulated if kind == "private" else True
        if kind == "private" and regulated and not nonregulated:
            context_known = True
        if context_known and set(required) <= kinds and all(not r.get("exceptions") for r in first_rules):
            rules.append(make("rank_requirements", effect="metadata", complete=True, required_kinds=required, scope="first_rank", supply="일반공급",
                              completion_basis="validated_source_rank_table", quote=" / ".join(r["evidence_text"] for r in first_rules), page=first_rules[0]["evidence_page"]))

    if not shinhee:
        from .supply_inventory import official_supplies
        inventory, inventory_status = official_supplies(pages,payload,make=make)
        if inventory:
            offered=list(dict.fromkeys(r["supply_type"] for r in inventory))
            rules = [r for r in rules if r["kind"] != "offered_supplies"]
            rules.append(make("offered_supplies",effect="metadata",supplies=inventory,inventory_status=inventory_status,quote=inventory[0].get("evidence_text") or "",page=inventory[0].get("evidence_page")))
            rules=[r for r in rules if r.get("effect")=="metadata" or not r.get("supply_type") or r["supply_type"] in offered]
        elif inventory_status in {"conflict", "partial"}:
            rules.append(make("offered_supplies", effect="metadata", supplies=[], inventory_status=inventory_status, quote="공식 모집표 물량 또는 열 해석이 충돌하거나 미확보입니다."))

    from .generic_admission import generic_private_admission
    admission_review = generic_private_admission(pages, digest=digest, payload=payload, rules=rules, offered=offered, sections=sections, make=make) if kind == "private" else None
    if shinhee:
        from .generic_family_admission import generic_family_admission
        family_review = generic_family_admission(pages, digest=digest, make=make)
        if family_review:
            preserved = [r for r in rules if r.get("effect") == "metadata" and r["kind"] != "offered_supplies"]
            family_review["rules"] = [*preserved, *family_review["rules"]]
            admission_review = family_review
    if admission_review:
        rules = admission_review["rules"]
        offered = admission_review.get("offered_supply_types", offered)

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
        remaining = ["재당첨·청약 제한 및 법령 예외", "소득·자산 분기" if supply != "일반공급" or kind == "national" else "신청 제한·연령 예외의 전체 검토"]
        if admission_review:
            remaining = admission_review["missing_topics"].get(supply, remaining)
        topics = [{"topic":r.get("label") or r["kind"],"status":"partial" if r["kind"] == "unparsed" else "verified","required":True,"rule_ids":[r["id"]]} for r in conditions]
        topics.extend({"topic":topic,"status":"missing","required":True,"rule_ids":[]} for topic in remaining)
        if admission_review:
            topics.extend(admission_review["exempt_topics"].get(supply, []))
            topics.extend(admission_review["conditional_topics"].get(supply, []))
        complete = bool(conditions and all(not t.get("required", True) or t["status"] in {"verified", "not_applicable"} for t in topics))
        scopes.append({"supply_type":supply,"complete":complete,"verified_rule_count":len(conditions),"topics":topics,"missing_topics":remaining,
                       **({"review_version": admission_review["review_version"], "reviewed_pages": admission_review["reviewed_pages"],
                           "completion_basis": admission_review.get("completion_basis", "document_structure_reviewed_standard_branch"), "reviewed_branches": ["standard"],
                           "unresolved_branches": [topic["topic"] for topic in admission_review["conditional_topics"].get(supply, [])]} if admission_review else {})})
    coverage_status = "complete" if scopes and all(s["complete"] for s in scopes) else "partial" if counts else "unsupported"
    rules.append(make("condition_coverage", effect="metadata", quote=cutoff_evidence["text"], page=cutoff_evidence["page"], status=coverage_status, offered_supply_types=offered, scopes=scopes, covered_supply_types=[s for s in offered if counts[s]], source="official_document_parser"))
    return {"rules": rules, "offered_supply_types": offered, "status": coverage_status, "parser_version": PARSER_VERSION}
