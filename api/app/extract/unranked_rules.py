"""Reviewed current application criteria for nonranked apartment offers.

The official method and current cutoff are established by the caller. A
reviewed identity/hash certifies inventory and completeness, not a collection
of phrases: unknown/changed documents retain only individually stated facts.
"""

from __future__ import annotations

import re

ADULT_LAW_URL = "https://www.law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joNo=0026&joBrNo=00&lsiSeq=286965&urlMode=lsScJoRltInfoR"
ADULT_LAW_TEXT = "제26조제5항: 국내에 거주하는 성년자로서 다음 각 호의 요건을 모두 갖춘 사람"


def normal(text):
    return re.sub(r"\s+", " ", text).strip()


def parse_unranked_conditions(pages, *, method, cutoff, reviewed, make):
    rules = []
    reviewed = reviewed or {}
    review = reviewed.get("unranked_review", {})
    source = {p["page"]: p for p in pages}
    regions = {
        "서울특별시": "11", "부산광역시": "26", "대구광역시": "27", "인천광역시": "28",
        "광주광역시": "29", "대전광역시": "30", "울산광역시": "31", "세종특별자치시": "36",
        "경기도": "41", "강원특별자치도": "51", "충청북도": "43", "충청남도": "44",
        "전북특별자치도": "52", "전라남도": "46", "경상북도": "47", "경상남도": "48", "제주특별자치도": "50",
    }

    def find(pattern, page_numbers=None):
        for p in pages:
            if page_numbers is not None and p["page"] not in page_numbers:
                continue
            match = re.search(pattern, normal(p["text"]))
            if match:
                return {"page": p["page"], "quote": match.group(0)}
        return None

    # Qualifying sentences must explicitly state applicant scope; statutory
    # family definitions or a sale address are not eligibility requirements.
    region = find(r"(?:무순위\s*\(?사후\)?\s*)?입주자모집공고일\s*현재\s*[^■]{0,120}?(?:" + "|".join(regions) + r")[^■]{0,180}?거주[^■]{0,80}?무주택\s*세대(?:구성원|주|의\s*세대주)")
    if region:
        names = [name for name in regions if re.search(re.escape(name) + r"(?:에|에서)?\s*거주", region["quote"])]
        capital = re.search(r"수도권\s*\(([^)]*)\)(?:에|에서)?\s*거주", region["quote"])
        if capital and {name for name in regions if name in capital[1]} == {"경기도", "서울특별시", "인천광역시"}:
            names = [name for name in regions if name in capital[1]]
        if len(names) == 1:
            name = names[0]
            rules.append(make("residence_region", supply="일반공급", region_code=regions[name], region_name=name, **region))
            rules.append(make("applicant_regions", effect="metadata", scope_complete=True, regions=[{"region_code": regions[name], "region_name": name}],
                              local_priority={"region_code": regions[name], "region_name": name, "min_months": 0, "criterion_date": cutoff}, **region))
        elif len(names) > 1:
            rules.append(make("any", supply="일반공급", label="신청 가능한 거주지역", conditions=[
                make("residence_region", region_code=regions[name], region_name=name, **region) for name in names], **region))
            rules.append(make("applicant_regions", effect="metadata", scope_complete=True, priority_applicable=False,
                regions=[{"region_code": regions[name], "region_name": name} for name in names], **region))
        rules.append(make("homeless", True, supply="일반공급", unit="boolean", **region))
        if re.search(r"무주택\s*세대(?:주|의\s*세대주)", region["quote"]):
            rules.append(make("household_head", True, supply="일반공급", **region))
    nationwide = find(r"입주자모집공고일\s*현재\s*전국에\s*거주하는\s*무주택세대구성원")
    if nationwide:
        rules.append(make("applicant_regions", effect="metadata", scope_complete=True, unrestricted=True,
                          domestic_only=True, priority_applicable=False, **nationwide))
        rules.append(make("domestic_residence", True, supply="일반공급", **nationwide))
        rules.append(make("homeless", True, supply="일반공급", **nationwide))

    foreign = find(r"(?:외국인\s*(?:청약불가|제외)|외국인은[^■]{0,150}청약이\s*불가)")
    if foreign:
        rules.append(make("citizenship", supply="일반공급", allowed_values=["korean"], **foreign))

    age = find(r"만\s*19세\s*이상인\s*분\s*또는\s*세대주인\s*미성년자\s*\([^)]*\)")
    if age:
        adult = make("age_min", 19, operator=">=", unit="years", **age)
        minor = make("all", conditions=[make("household_head", True, **age), make("unparsed", label="미성년 세대주의 부양 요건", text="자녀 양육 또는 형제자매 부양의 공식 요건과 증빙을 확인해야 합니다.", **age)], label="미성년 세대주의 공식 예외", **age)
        rules.append(make("any", supply="일반공급", conditions=[adult, minor], label="성년 또는 공고의 미성년 세대주", **age))
    elif review.get("adult_law") and method == "unranked_after":
        # Exact source review establishes Art19(5)/26(5) applicability. The
        # document's omitted age is completed by the current official law,
        # never by assuming that all no-account offers have the same age.
        law = {"quote": ADULT_LAW_TEXT, "page": None, "evidence_url": ADULT_LAW_URL, "evidence_section": "제26조제5항",
               "verification_basis": "official_law_review", "law_effective_date": "2026-06-15", "applied_document_url": reviewed["document_url"],
               "applied_document_page": review["qualification_page"]}
        adult = make("age_min", 19, operator=">=", unit="years", **law)
        minor = make("unparsed", label="미성년자의 공식 성년 예외", text="19세 미만인 경우 법률상 성년 인정 사유와 증빙을 확인해야 합니다.", **law)
        rules.append(make("any", supply="일반공급", conditions=[adult, minor], label="법정 성년", **law))

    overseas = find(r"해외체류기간이\s*계속하여\s*90일을\s*초과한\s*기간[^■]{0,500}?단,\s*「주택공급에\s*관한\s*규칙」\s*제4조제8항[^■]{0,220}?국내에\s*거주하고\s*있는\s*것으로\s*봅니다")
    if not overseas and review.get("overseas_reviewed_page") in source:
        # A reviewed PDF draws the numerals after the sentence in its content
        # stream. The page/hash review establishes the number and exception;
        # this fallback is never applied to an unreviewed or corrected file.
        p = source[review["overseas_reviewed_page"]]
        text = normal(p["text"])
        if all(term in text for term in ("해외체류기간", "90", "초과한 기간", "생업", "국내에 거주하고 있는 것으로 봅니다")):
            start = text.index("해외체류기간")
            stop = text.index("국내에 거주하고 있는 것으로 봅니다", start)
            overseas = {"page":p["page"], "quote":text[start:stop+28]}
    if overseas:
        rules.append(make("overseas_residence", supply="일반공급", max_continuous_days=90, livelihood_exception=True,
                          value_basis="continuous_days_including_reentry_within_7_days", **overseas))

    # Restriction facts are scoped and project-specific. An answer concerning
    # a different apartment or a different household must not be reused.
    restrictions = review.get("restrictions", [])
    project_match = find(r"최초\s*주택관리번호는\s*(\d{10})")
    project_id = re.search(r"\d{10}", project_match["quote"]).group(0) if project_match else None
    for definition in restrictions:
        anchor = find(definition["pattern"], definition.get("pages"))
        if not anchor:
            continue
        restriction = definition["restriction"]
        fields = {"restriction": restriction, "scope": definition.get("scope", "applicant"), "label": definition["label"]}
        if restriction.startswith("prior_project_"):
            if not project_id or project_id != review.get("original_project_id"):
                continue
            fields["project_id"] = project_id
            fields["project_title"] = reviewed["title"]
            if restriction == "prior_project_contract":
                fields["include_additional_resident"] = True
        rules.append(make("application_restriction", False, supply="일반공급", **fields, **anchor))

    # Changed documents can still supply explicit individual facts, but only
    # hash review with the complete required set certifies the whole scope.
    actual = {r["kind"] for r in rules if r.get("effect") != "metadata"}
    restriction_kinds = {r.get("restriction") for r in rules if r["kind"] == "application_restriction"}
    expected = set(review.get("required_kinds", []))
    expected_restrictions = {r["restriction"] for r in restrictions}
    complete = bool(review and expected and expected <= actual and expected_restrictions <= restriction_kinds and
                    all(p in source for p in reviewed.get("reviewed_pages", [])) and cutoff == reviewed.get("announcement_date"))
    return {"rules": rules, "offered_supply_types": ["일반공급"], "complete": complete,
            "missing_topics": [] if complete else ["공고별 제한·연령 예외 및 전체 신청요건 검토"]}
