"""Nonranked eligibility from operative clauses, without notice catalogs.

Administrative names and legal meanings are reference data. No project, hash,
expected inventory or fixed page selects a condition. Unknown restriction
entries remain a source gap instead of silently granting eligibility.
"""
from __future__ import annotations
import re
from decimal import Decimal
from .application_regions import explicit_applicant_regions, region_catalog

ADULT_LAW_URL = "https://www.law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joNo=0026&joBrNo=00&lsiSeq=286965&urlMode=lsScJoRltInfoR"
ADULT_LAW_TEXT = "제26조제5항: 국내에 거주하는 성년자로서 다음 각 호의 요건을 모두 갖춘 사람"
REVIEW_VERSION = "generic-admission-unranked-2026-10-11-v2"
ACCOUNT_WAIVER = r"청약통장\s*(?:(?:가입여부)?\s*(?:와|에)?\s*(?:무관|관계없이)|이?\s*필요(?:없|하지\s*않))"


def normal(text):
    # PDF line wraps can split legal tokens without changing their meaning.
    # Join only legal vocabulary, keeping sentence and table boundaries.
    for token in ("입주자모집공고일", "무주택세대구성원", "무주택세대주", "해외체류기간", "공급질서교란자", "주택관리번호"):
        text = re.sub(r"\s*".join(map(re.escape, token)), token, text)
    return re.sub(r"\s+", " ", text).strip()


def _qualification_section(pages):
    active = False
    lines = []
    for page in pages:
        for line in page["text"].splitlines():
            value = normal(line)
            if re.match(r"^\d+(?:[-.]\d+)?\.?\s+(?:청약\s*자격|일반공급\s*대상자)", value):
                active = True
            elif active and re.match(r"^\d+(?:[-.]\d+)?\.?\s+[가-힣A-Z]", value):
                return lines, True
            if active:
                lines.append({"page": page["page"], "text": line})
    # Extracted fixtures/documents may end at the final table page. The
    # explicit selection-method row also closes the eligibility table.
    bounded = any(re.search(r"당첨자\s*(?:및|선정)|예비입주자\s*선정", normal(row["text"])) for row in lines)
    return lines, bounded


def parse_unranked_conditions(pages, *, method, cutoff, reviewed=None, make):
    # reviewed is retained only for caller compatibility.
    rules, missing = [], []
    section, bounded = _qualification_section(pages)
    provinces = {row["name"]: row["code"] for row in region_catalog()["provinces"]}
    qualification_pages = {}
    for line in section:
        qualification_pages.setdefault(line["page"], []).append(line["text"])
    restriction_pages = [{"page": page, "text": "\n".join(lines)} for page, lines in qualification_pages.items()]

    def find(pattern, source=None):
        for page in pages if source is None else source:
            match = re.search(pattern, normal(page["text"]))
            if match:
                return {"page": page["page"], "quote": match.group(0)}
        return None

    # The numbered applicant table defines this route. A cover summary or a
    # generic law-comparison table must not replace its applicant scope.
    applicant_pages = restriction_pages if section else pages
    regions = explicit_applicant_regions(applicant_pages, cutoff=cutoff, make=make, provinces=provinces, method=method)
    common_regions = [region for region in explicit_applicant_regions(pages, cutoff=cutoff, make=make, provinces=provinces, method=method)
                      if not region.get("supply_type")]
    region_scope = lambda region: (tuple(sorted(row["region_code"] for row in region.get("regions", []))),
                                   bool(region.get("unrestricted")))
    if regions:
        operative_scopes = {region_scope(region) for region in regions}
        # A differently ordered summary is the same OR scope. A genuinely
        # contradictory current applicant clause still prevents certification.
        regions.extend(region for region in common_regions if region_scope(region) not in operative_scopes)
    else:
        # Some cancellation documents put the common residence clause before
        # their subtype tables. Keep that verified clause even when the table
        # heading/layout cannot establish a complete general branch.
        regions = common_regions
    for region in regions:
        priorities = [candidate for candidate in common_regions
                      if region_scope(candidate) == region_scope(region) and candidate.get("local_priority")]
        distinct = []
        for candidate in priorities:
            if candidate["local_priority"] not in distinct:
                distinct.append(candidate["local_priority"])
        if len(distinct) > 1 or (distinct and region.get("local_priority") and region["local_priority"] != distinct[0]):
            region["scope_complete"] = False
            missing.append("현재 신청자격 문단 사이의 지역 우선배정 조건 불일치")
        elif distinct and not region.get("local_priority"):
            # General notes can state a priority that the applicant table
            # abbreviates. Keep its separate source proof with the same scope.
            region["priority_applicable"] = True
            region["local_priority"] = dict(distinct[0])
            region["regional_priority_evidence"] = {key: priorities[0][key] for key in
                ("evidence_page", "evidence_text", "evidence_url", "document_hash") if key in priorities[0]}
    selection = _clause(section, r"당첨자\s+(?:및\s+)?[^■]{0,90}■\s*한국부동산원\s*입주자\s*선정\s*프로그램에\s*의해\s*주택형별\s*무작위\s*추첨으로\s*무순위\s*\(사후\)\s*당첨자\s*선정\s*및\s*동[·ㆍ]?호수\s*배정")
    if (selection and not any(region.get("local_priority") or region.get("scope_complete") is False for region in regions)
            and not re.search(r"지역[^■]{0,60}(?:우선|선정)|우선공급", normal(" ".join(row["text"] for row in section)))):
        for region in regions:
            # All applicants in the route share the printed random draw.
            # Attach that selection evidence rather than infer from the site.
            region["priority_applicable"] = False
            selection_fact = make("regional_selection", effect="metadata", **selection)
            region["regional_selection_evidence"] = {key: selection_fact[key] for key in
                ("evidence_page", "evidence_text", "evidence_url", "document_hash") if key in selection_fact}
    rules.extend(regions)
    scopes = {(tuple(sorted(r["region_code"] for r in rule.get("regions", []))), bool(rule.get("unrestricted"))) for rule in regions}
    if len(scopes) > 1:
        missing.append("현재 신청자격 문단 사이의 거주지역 조건 불일치")
        for region in regions:
            region["scope_complete"] = False
    if regions:
        source = regions[0]
        evidence = {"page": source.get("evidence_page"), "quote": source["evidence_text"]}
        eligible = source.get("regions", [])
        if len(eligible) == 1:
            rules.append(make("residence_region", supply="일반공급", **eligible[0], **evidence))
        elif eligible:
            rules.append(make("any", supply="일반공급", label="신청 가능한 거주지역", conditions=[make("residence_region", **region, **evidence) for region in eligible], **evidence))
        elif source.get("unrestricted") and source.get("domestic_only"):
            rules.append(make("domestic_residence", True, supply="일반공급", **evidence))
    else:
        missing.append("현재 신청자격 문단의 거주지역 조건")
    homeless = find(r"입주자모집공고일\s*현재[^■]{0,350}?무주택\s*세대(?:구성원|주|의\s*세대주)", applicant_pages)
    if homeless:
        rules.append(make("homeless", True, supply="일반공급", unit="boolean", **homeless))
    else:
        missing.append("현재 일반공급 대상자의 주택 소유 조건")
    head = find(r"입주자모집공고일\s*현재[^■]{0,350}?무주택\s*세대(?:의\s*세대)?주", applicant_pages)
    if head:
        rules.append(make("household_head", True, supply="일반공급", **head))
    foreign = find(r"(?:외국인\s*(?:청약불가|제외)|외국인은[^■]{0,180}?청약이?\s*불가)")
    if foreign:
        rules.append(make("citizenship", supply="일반공급", allowed_values=["korean"], **foreign))
    else:
        missing.append("현재 신청자격의 국적 조건")
    age = find(r"만\s*\d+\s*세\s*이상인?\s*분\s*또는\s*세대주인\s*미성년자\s*\([^)]*\)")
    if age:
        adult_age = int(re.search(r"만\s*(\d+)\s*세", age["quote"])[1])
        adult = make("age_min", adult_age, operator=">=", unit="years", **age)
        minor = make("all", conditions=[make("household_head", True, **age), make("unparsed", label="미성년 세대주의 부양 요건", text="자녀 양육 또는 형제자매 부양의 공식 요건과 증빙을 확인해야 합니다.", **age)], label="미성년 세대주의 공식 예외", **age)
        rules.append(make("any", supply="일반공급", conditions=[adult, minor], label="성년 또는 공고의 미성년 세대주", **age))
    elif (adult := find(r"(?:입주자모집공고일\s*현재|대상자)[^■]{0,350}?만\s*\d+\s*세\s*이상(?:의)?\s*(?:성년자|인\s*분)")):
        rules.append(make("age_min", int(re.search(r"만\s*(\d+)\s*세", adult["quote"])[1]), operator=">=", unit="years", supply="일반공급", **adult))
    elif method == "unranked_after" and homeless:
        applicable = find(r"본\s*(?:입주자모집공고|주택|아파트)[^■]{0,45}?20\d{2}\.\d{1,2}\.\d{1,2}\.\s*시행된\s*「주택공급에\s*관한\s*규칙」이\s*적용됩니다")
        if applicable:
            applied = re.search(r"(20\d{2})\.(\d{1,2})\.(\d{1,2})", applicable["quote"])
            law = {"quote": ADULT_LAW_TEXT, "page": None, "evidence_url": ADULT_LAW_URL, "evidence_section": "제26조제5항", "verification_basis": "official_law_review", "law_effective_date": "-".join((applied[1], applied[2].zfill(2), applied[3].zfill(2))), "applied_document_page": applicable["page"]}
            adult = make("age_min", 19, operator=">=", unit="years", **law)
            minor = make("unparsed", label="미성년자의 공식 성년 예외", text="19세 미만인 경우 법률상 성년 인정 사유와 증빙을 확인해야 합니다.", **law)
            rules.append(make("any", supply="일반공급", conditions=[adult, minor], label="법정 성년", **law))
        else:
            missing.append("연령 조건 또는 적용 법령의 성년 조건")
    else:
        missing.append("성년·미성년 신청자의 조건")

    overseas = find(r"해외체류기간이\s*계속하여\s*\d+일을\s*초과한\s*기간[^■]{0,1100}?단,\s*「주택공급에\s*관한\s*규칙」\s*제4조제8항[^■]{0,280}?국내에\s*거주하고\s*있는\s*것으로\s*봅니다")
    if overseas:
        duration = re.search(r"계속하여\s*(\d+)일", overseas["quote"])
        reentry = re.search(r"입국\s*후\s*(\d+)일\s*내\s*동일국가\s*재출국", overseas["quote"])
        if reentry:
            rules.append(make("overseas_residence", supply="일반공급", max_continuous_days=int(duration[1]), livelihood_exception="생업" in overseas["quote"], value_basis=f"continuous_days_including_reentry_within_{reentry[1]}_days", reentry_same_country=True, reentry_within_days=int(reentry[1]), **overseas))
        else:
            missing.append("해외 연속체류의 재입국·생업 예외 조건")
    elif find(r"장기\s*해외\s*체류[^■]{0,160}?(?:청약|신청)[^■]{0,70}?불가"):
        missing.append("해외 연속체류 기간·재입국·생업 예외 조건")

    project = find(r"최초\s*(?:주택관리|사업)번호는?\s*\d{10}")
    project_id = re.search(r"\d{10}", project["quote"])[0] if project else None
    patterns = [
        ("prior_project_contract", "해당 사업의 과거 계약·추가입주자 이력", r"동\s*주택에\s*당첨되어\s*계약을\s*체결한\s*분\s*또는\s*예비입주자\s*중\s*추가입주자로\s*선정된\s*분"),
        ("prior_project_winner", "해당 사업의 과거 당첨 이력", r"동\s*주택에\s*당첨되었으나\s*계약을\s*체결하지\s*않은\s*분"),
        ("ineligible_restriction_active", "부적격 당첨 제한기간", r"부적격\s*당첨자로서\s*그\s*제한기간\s*중에\s*있는\s*분"),
        ("resale_restriction_active", "공급질서교란 제한기간", r"공급질서\s*교란자로서\s*그\s*제한기간\s*중에\s*있는\s*분"),
        ("rewinning_restriction_active", "재당첨 제한기간", r"과거\s*재당첨\s*제한\s*대상\s*주택에\s*당첨되어\s*현재\s*그\s*기간\s*중에\s*있는\s*분\s*및\s*그\s*세대원"),
    ]
    known_clauses = []
    for restriction, label, pattern in patterns:
        anchor = find(pattern, restriction_pages)
        if not anchor:
            continue
        known_clauses.append(anchor["quote"])
        fields = {"restriction": restriction, "scope": "household" if restriction == "rewinning_restriction_active" else "applicant", "label": label}
        if restriction.startswith("prior_project_"):
            if not project_id:
                missing.append("원문이 제한하는 최초 사업번호")
                continue
            fields["project_id"] = project_id
            if restriction == "prior_project_contract":
                fields["include_additional_resident"] = True
        rules.append(make("application_restriction", False, supply="일반공급", **fields, **anchor))
    rewinning = find(r"기존\s*주\s*택\s*당첨으로\s*인해\s*재당첨\s*제한\s*기간\s*내에\s*있는\s*분\s*및\s*그\s*(?:배우자|세대에\s*속한\s*분)[^■]{0,70}?청약\s*(?:신청할\s*수\s*없습니다|이\s*불가합니다)")
    if rewinning and not any(r.get("restriction") == "rewinning_restriction_active" for r in rules):
        rules.append(make("application_restriction", False, supply="일반공급", restriction="rewinning_restriction_active", scope="applicant_spouse" if "배우자" in rewinning["quote"] else "household", label="재당첨 제한기간", **rewinning))
    combined = find(r"제56조제1항에\s*따른\s*입주자자격\s*제한기간\s*중에\s*있는\s*분\s*\(공급질서교란자\s*또는\s*전매제한\s*위반자\)[^■]{0,100}?제58조제3항에\s*따른\s*입주자선정\s*제한기간\s*중에\s*있는\s*분\s*\(부적격\s*당첨자\)[^■]{0,100}?청약할\s*수\s*없습니다")
    if combined:
        for restriction, label in (("resale_restriction_active", "공급질서교란·전매위반 제한기간"), ("ineligible_restriction_active", "부적격 당첨 제한기간")):
            if not any(r.get("restriction") == restriction for r in rules):
                rules.append(make("application_restriction", False, supply="일반공급", restriction=restriction, scope="applicant", label=label, **combined))
    if not find(ACCOUNT_WAIVER):
        missing.append("청약통장 가입 요건·면제")
    if not section or not bounded:
        missing.append("신청자격·대상자 문단의 전체 범위")
    section_text = normal(" ".join(row["text"] for row in section))
    table = re.search(r"아래에\s*해당하는\s*경우\s*청약\s*신청\s*불가(.+?)(?:당첨자\s*(?:및|선정)|예비입주자\s*선정)", section_text)
    # Skip the heading, whose title itself contains '당첨자 선정'.
    qualification_body = section_text[section_text.find("■"):] if "■" in section_text else section_text
    qualification = re.split(r"아래에\s*해당하는\s*경우|당첨자\s*(?:■|및|선정)", qualification_body)[0]
    for clause in qualification.split("■")[1:]:
        text = normal(clause)
        recognised = bool(re.search(r"입주자모집공고일\s*현재[^■]{0,350}?무주택\s*세대(?:구성원|주|의\s*세대주)", text) or
                          re.search(ACCOUNT_WAIVER, text) or
                          re.search(r"외국인은[^■]{0,180}?청약이?\s*불가", text))
        if text and (not recognised or re.search(r"소득|자산|추천|혼인", text)):
            missing.append("신청자격 표의 미처리 조항: " + text[:130])
    if table:
        # Table-label cells may be interleaved into the PDF's restriction text.
        clean = lambda text: re.sub(r"\s+", "", re.sub(r"청약신청|제한", "", text))
        for entry in re.split(r"\s+-\s+", table[1]):
            value = clean(entry)
            if value and not any(value == clean(known) for known in known_clauses):
                missing.append("청약신청 제한 표의 미처리 조항: " + normal(entry)[:130])
    elif not combined:
        missing.append("현재 신청자의 당첨·계약·부적격·공급질서 제한 조항")
    restrictions = {r.get("restriction") for r in rules if r["kind"] == "application_restriction"}
    expected = {"ineligible_restriction_active", "resale_restriction_active"}
    if method == "unranked_after":
        expected |= {"prior_project_contract", "prior_project_winner"}
    if not expected <= restrictions:
        missing.append("현재 신청자의 당첨·계약 및 제한기간 조항")
    missing = list(dict.fromkeys(missing))
    return {"rules": rules, "offered_supply_types": ["일반공급"], "complete": not missing, "missing_topics": missing,
            "review_version": REVIEW_VERSION, "reviewed_pages": sorted({row["page"] for row in section})}


def _special_sections(pages, offered):
    """Operative numbered applicant tables, including their continued pages."""
    result, current = {}, None
    for page in pages:
        for line in page["text"].splitlines():
            text = normal(line)
            heading = re.match(r"^\d+(?:[-.]\d+)*\.?\s+(.+)$", text)
            if heading:
                title = heading[1]
                supply = next((name for name in offered if title.startswith(name) and name != "일반공급"), None)
                current = [] if supply else None
                if supply:
                    result.setdefault(supply, []).append(current)
            if current is not None:
                current.append({"page": page["page"], "text": line})
    return result


def _clause(lines, pattern):
    body, offsets = "", []
    for line in lines:
        offsets.append((len(body), line["page"]))
        body += normal(line["text"]) + " "
    match = re.search(pattern, body)
    if not match:
        return None
    page = next(page for offset, page in reversed(offsets) if offset <= match.start())
    return {"page": page, "quote": match[0].strip()}


def _special_financial(lines, *, supply, make):
    """Read the printed income/asset alternative, never annual constants."""
    from .generic_admission import _income_extension, _income_rows
    pages = {}
    for line in lines:
        pages.setdefault(line["page"], []).append(line["text"])
    financial_pages = [{"page": page, "text": "\n".join(text)} for page, text in pages.items()]
    rows, year, sizes = _income_rows(financial_pages)
    policy = _clause(lines, r"(\d+)%\s*초과하나,\s*[^■]{0,120}?부동산\s*가액\s*\(\s*([\d.]+)\s*억원\s*\)\s*충족")
    if not policy or not rows or year is None:
        return [], ["현재 소득·자산 대안의 비율별 가구원 표·적용 연도"]
    percent = int(re.search(r"(\d+)%", policy["quote"])[1])
    if percent not in rows:
        return [], ["현재 소득·자산 대안의 상한 비율과 소득표 대조"]
    declared_asset = int(Decimal(re.search(r"([\d.]+)\s*억원", policy["quote"])[1]) * 100000000)
    asset = _clause(lines, r"부동산\s*\(건물\+토지\)[^■]{0,200}?([\d,]+)억\s*([\d,]+)만원\s*[^■]{0,70}?이하")
    if not asset:
        # PDF asset-table columns can interleave building-price descriptions
        # between the '부동산' label, '(건물+토지)' and its household cap.
        # Require the closed table header and household scope, then reconcile
        # its independently printed amount with the policy alternative above.
        asset = _clause(lines, r"자산보유기준\s*구분\s*금액\s*내용[^■]{0,650}?부동산[^■]{0,120}?\(건물\+토지\)[^■]{0,150}?청약자\s*및\s*([\d,]+)억\s*([\d,]+)만원[^■]{0,150}?그\s*세대원\s*전부\s*이하")
    if not asset:
        return [], ["현재 공고의 세대 부동산 산정 범위·가격 상한표"]
    amount = re.search(r"([\d,]+)억\s*([\d,]+)만원", asset["quote"])
    maximum = int(amount[1].replace(",", "")) * 100000000 + int(amount[2].replace(",", "")) * 10000
    if maximum != declared_asset:
        return [], ["소득 대안과 부동산 기준표의 상한 불일치"]
    scope = _clause(lines, r"가구원수\s*산정\s*기준[^■]{0,1400}?소득산정\s*대상에서\s*제외")
    ascendant = re.search(r"최근\s*(\d+)년\s*이상\s*계속하여\s*공급신청자", scope["quote"] if scope else "")
    adult = re.search(r"가구원\s*중\s*만\s*(\d+)세\s*이상인\s*성년자", scope["quote"] if scope else "")
    if not scope or not ascendant or not adult:
        return [], ["소득 산정 가구원·직계존속 거주기간·소득 대상 범위"]
    extension = _income_extension(financial_pages, percent=percent, rows=rows)
    issues = [extension["extra_person_formula_issue"]] if extension.get("extra_person_formula_verified") is False else []
    income = make("monthly_income_max_krw", supply=supply, min_household_size=sizes[0],
                  household_size_basis="official_income_household", value_basis="household_monthly_income",
                  income_table=rows[percent]["table"], income_percent=percent, **extension, **rows[percent]["evidence"])
    property_rule = make("real_estate_max_krw", maximum, supply=supply, operator="<=", asset_basis="real_estate",
                         household_scope="all_legal_household_members", **asset)
    financial = make("any", supply=supply, label="월평균소득 또는 부동산 기준", conditions=[income, property_rule], **policy)
    scope_rule = make("income_household_scope", supply=supply, effect="metadata", income_year=year,
                      include_fetuses="태아" in scope["quote"], ascendant_same_register_min_months=int(ascendant[1]) * 12,
                      income_member_min_age=int(adult[1]), include_qualifying_minor_head="세대주인 미성년자" in scope["quote"],
                      exclude_missing_cancelled_registration="말소" in scope["quote"], asset_household_scope="all_legal_household_members", **scope)
    return [financial, scope_rule], issues


def parse_nonranked_special_conditions(pages, offered, make):
    """Supported facts from actual residual special-supply applicant tables.

    Each subtype has independent source gaps. General-supply conditions cannot
    establish a special route, and an extracted amount cannot certify the
    whole document's legal exemptions.
    """
    special = [name for name in offered if name != "일반공급"]
    sections = _special_sections(pages, special)
    all_lines = [{"page": page["page"], "text": line} for page in pages for line in page["text"].splitlines()]
    rules, missing, reviewed_pages, conditional = [], {}, {}, {}
    for supply in special:
        missing[supply], conditional[supply] = [], []
        candidates = [lines for lines in sections.get(supply, []) if _clause(lines, r"입주자모집공고일\s*현재[^■]{0,400}?무주택")]
        if len(candidates) != 1:
            missing[supply].append("현재 공급유형의 신청자격 문단 미확보 또는 중복 문단 불일치")
            reviewed_pages[supply] = []
            continue
        lines = candidates[0]
        reviewed_pages[supply] = sorted({line["page"] for line in lines})
        e = lambda pattern: _clause(lines, pattern)
        homeless = e(r"입주자모집공고일\s*현재[^■]{0,350}?무주택세대(?:구성원|주)")
        home = make("homeless", True, supply=supply, **homeless)
        head = e(r"입주자모집공고일\s*현재[^■]{0,350}?무주택세대주")
        if head:
            rules.append(make("household_head", True, supply=supply, **head))
        birth = _clause(all_lines, r"출산특례[^■]{0,1200}?기존주택\s*처분\s*조건[^■]{0,180}?청약신청\s*가능")
        if birth and not _clause(all_lines, r"생애최초\s*특별공급만[^■]{0,400}?(?:출산특례|출산\s*특례)[^■]{0,100}?(?:불가|적용되지|적용할\s*수\s*없)"):
            description = "출산특례의 자녀·특별공급 당첨 및 기존주택 처분 조건"
            home["exceptions"] = [make("unparsed", supply=supply, label=description, text=description, **birth)]
            conditional[supply].append(description)
        rules.append(home)
        if supply == "노부모부양 특별공급":
            support = e(r"만\s*(\d+)세\s*이상의\s*직계존속[^■]{0,100}?(\d+)년\s*이상\s*계속하여\s*부양[^■]{0,180}?등재[^■]{0,80}?한\s*분")
            if support:
                age, years = re.search(r"만\s*(\d+)세.+?(\d+)년", support["quote"]).groups()
                rules.extend([make("parent_age_min", int(age), supply=supply, operator=">=", **support),
                              make("parent_support_months_min", int(years) * 12, supply=supply, operator=">=", **support),
                              make("parent_same_register", True, supply=supply, **support)])
            else:
                missing[supply].append("부양 대상 연령·연속 부양기간·동일 등본 조건")
            spouse = e(r"피부양자의\s*배우자도\s*무주택자이어야\s*함")
            ownership = e(r"직계존속\s*\(피부양자의\s*배우자\s*포함\)이\s*주택을\s*소유한\s*경우\s*유주택자")
            if spouse and ownership:
                rules.extend([make("parent_owns_home", False, supply=supply, **ownership),
                              make("parent_spouse_owns_home", False, supply=supply, **spouse)])
            else:
                missing[supply].append("피부양자·배우자의 별도 주택 소유 기준")
        elif supply == "생애최초 특별공급":
            past = e(r"생애최초로\s*주택을\s*구입하는\s*분[^■]{0,650}?모든\s*세대구성원이\s*과거\s*주택을\s*소유한\s*사실이\s*없는\s*경우[^■]{0,650}")
            if past:
                spouse_disposal = bool(re.search(r"배우자가\s*혼인\s*전\s*주택을\s*소유하였다가\s*혼인\s*전\s*처분한\s*이력은\s*배제", past["quote"]))
                history = make("never_owned_home", True, supply=supply, scope="household", exclude_spouse_pre_marriage_disposed=spouse_disposal, **past)
                ownership_exception = _clause(all_lines, r"만\s*\d+세\s*이상의\s*직계존속[^■]{0,350}?주택\s*또는\s*분양권[^■]{0,180}?(?:노부모|부양자)[^■]{0,80}?제외")
                if ownership_exception:
                    topic = "생애최초의 법정 과거 주택 소유 예외 적용 범위"
                    history["exceptions"] = [make("unparsed", supply=supply, label=topic, text=topic, **ownership_exception)]
                    conditional[supply].append(topic)
                rules.append(history)
            else:
                missing[supply].append("생애최초 세대의 과거 주택 소유·배우자 혼인 전 처분 예외")
            family = e(r"아래\s*‘가’\s*또는\s*‘나’[^■]{0,1700}?직계존속과\s*같은\s*세대를\s*구성하는\s*경우를\s*말함")
            maximum = re.search(r"단독세대\s*신청자는\s*전용면적\s*(\d+(?:\.\d+)?)\s*㎡\s*이하", family["quote"] if family else "")
            if family and maximum and "동일한 주민등록표등본" in family["quote"]:
                rules.append(make("first_home_family", True, supply=supply, solo_max_area_sqm=float(maximum[1]),
                                  include_adoption="입양자녀" in family["quote"], include_pregnancy="태아" in family["quote"],
                                  unmarried_child_required=True, unmarried_applicant_child_same_register=True,
                                  non_solo_requires_ascendant=True, **family))
            else:
                missing[supply].append("혼인·동일 등본 미혼 자녀·단독 및 비단독 1인가구 면적 분기")
            tax = e(r"입주자모집공고일\s*현재\s*근로자\s*또는\s*자영업자[^■]{0,1500}?배우자\s*또는\s*세대원의\s*납부실적은\s*배제")
            years = re.search(r"(\d+)년\s*이상\s*소득세를\s*납부", tax["quote"] if tax else "")
            recent = re.search(r"과거\s*(\d+)년\s*내에?\s*소득세", tax["quote"] if tax else "")
            if tax and years and recent:
                rules.append(make("first_home_tax_activity", True, supply=supply, tax_years_min=int(years[1]),
                                  recent_tax_months=int(recent[1]) * 12, includes_tax_exemption="납부의무액이 없는 경우" in tax["quote"],
                                  tax_years_basis="separate_calendar_years_not_60_months", **tax))
            else:
                missing[supply].append("본인 소득세 납부 연수·최근 납부기간·납부의무 면제 조건")
            financial, issues = _special_financial(lines, supply=supply, make=make)
            rules.extend(financial)
            missing[supply].extend(issues)
        else:
            missing[supply].append("현재 공급유형의 추천·가족·소득 요건과 공식 면제 분기")
        # Common special-supply history and exceptions need their own modeled
        # subjects. General-route restriction nodes do not prove these facts.
        missing[supply].append("특별공급 횟수 제한의 확인 대상과 혼인·출산 등 공식 예외 적용 범위")
        missing[supply] = list(dict.fromkeys(missing[supply]))
    return {"rules": rules, "missing_topics": missing, "conditional_topics": conditional,
            "reviewed_pages": reviewed_pages, "review_version": REVIEW_VERSION}
