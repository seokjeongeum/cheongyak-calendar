"""Reviewed clauses from the current Incheon Gajeong 2 B2 residual offer.

The April first-offer winner and contract clause is an ownership check, not a
ban on past wins. Instructions and post-selection paperwork remain metadata.
"""
from __future__ import annotations

import re

GAJEONG_HASH = "acef66815d56e98917f7d3ae2129de9dc6aede9827a4d79a948530373c66ea54"
GAJEONG_PROJECT = "LH-INCHEON-GAJEONG2-B2"
GAJEONG_SUPPLY_URL = "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do?panId=0000061183&ccrCnntSysDsCd=02&uppAisTpCd=05&aisTpCd=05&mi=1027"

# The whole 19-page document was reviewed. These are the operative applicant
# sections, including the exceptions, current restrictions and later notices.
GAJEONG_REVIEW = {
    "pages": list(range(1, 20)),
    "topics": ["age", "domestic_residence", "citizenship", "home_ownership",
               "overseas_residence", "original_contract_ownership", "application_restrictions"],
    "branches": [
        {"branch_id": "adult", "label": "성년 신청자", "requirements": ["age", "domestic_residence", "citizenship", "home_ownership", "overseas_residence", "original_contract_ownership", "application_restrictions"]},
        {"branch_id": "minor_household_head", "label": "미성년 세대주 예외", "requirements": ["미성년 세대주·동일 등본의 부양 자녀 또는 형제자매", "domestic_residence", "citizenship", "home_ownership", "overseas_residence", "original_contract_ownership", "application_restrictions"]},
        {"branch_id": "overseas_livelihood", "label": "생업 목적 해외 체류 예외", "requirements": ["본인만 생업 목적 해외 체류", "단독세대주·동거인의 세대원 제외", "나머지 확인 대상 세대원 국내 거주"]},
        {"branch_id": "ownership_exceptions", "label": "공식 주택 소유 예외", "requirements": ["제53조 12개 예외의 실제 취득·처분·세대·가격·면적 사실"]},
    ],
    "exempt_topics": ["account", "income", "assets", "prior_win", "rewinning_restriction"],
    "reviewed_section_pages": [1, 2, 8, 9, 10, 13],
}


def gajeong_admission(pages, *, digest, make):
    if digest != GAJEONG_HASH:
        return None
    source = {p["page"]: re.sub(r"\s+", " ", p["text"]).strip() for p in pages}

    def evidence(page, pattern):
        match = re.search(pattern, source.get(page, ""))
        return {"page": page, "text": match.group(0)} if match else None

    facts = []
    overseas = evidence(1, r"입주자모집공고일을\s*기준으로\s*국외에\s*계속하여\s*90일을\s*초과하여.{0,480}?청약\s*가능\)")
    exception = evidence(2, r"\(5\)\s*세대원\s*중\s*주택공급신청자만.{0,250}?단독세대주\s*또는\s*동거인의\s*세대원.{0,60}?해당없음\)")
    returned = evidence(2, r"\(3\).{0,230}?청약신청\s*가능.{0,170}?계속\s*거주한\s*것으로\s*간주")
    if overseas and exception and returned:
        facts.append(("overseas_residence", make("overseas_residence", supply="일반공급", evidence=overseas,
            max_continuous_days=90, value_basis="continuous_days_including_reentry_within_7_days",
            currently_abroad_only=True, reentry_same_country=True, reentry_within_days=7,
            livelihood_exception=True, livelihood_exception_requires_family=True,
            livelihood_exception_excludes=["sole_household_head", "cohabitant_household_member"],
            exception_evidence_text=exception["text"], exception_evidence_page=2,
            return_evidence_text=returned["text"], return_evidence_page=2)))
    ownership = evidence(8, r"단,\s*최초\s*입주자모집\(2026\.04\.15\).{0,250}?신청\s*불가능합니다")
    permission = evidence(8, r"공고일\(2026\.09\.23\)\s*기준\s*최초\s*입주자모집공고\(2026\.04\.15\).{0,250}?신청\s*가능합니다")
    if ownership and permission:
        facts.append(("original_contract_ownership", make("original_project_contract_ownership", supply="일반공급", evidence=ownership,
            project_id=GAJEONG_PROJECT, scope="applicant", original_announcement_date="2026-04-15",
            requires_original_winning=True, ownership_effect="contract_date",
            first_winning_alone_allowed=True, ineligible_winning_alone_allowed=True,
            permission_evidence_text=permission["text"], permission_evidence_page=8)))
    restriction = evidence(10, r"주택의\s*전매행위\s*제한을\s*위반한\s*경우.{0,140}?입주자격을\s*제한합니다")
    if restriction:
        facts.append(("application_restrictions", make("application_restriction", False, supply="일반공급", evidence=restriction,
            restriction="resale_restriction_active", scope="applicant")))

    metadata = []
    total = evidence(1, r"공급대상\s*:\s*공공분양주택\s*([\d,]+)세대\s*중\s*잔여\s*([\d,]+)세대\s*\([^)]{0,100}\)")
    inventory = []
    if total:
        numbers = re.search(r"([\d,]+)세대\s*중\s*잔여\s*([\d,]+)세대", total["text"])
        metadata.append(make("supply_inventory_summary", effect="metadata", evidence=total,
            total_households=int(numbers[1].replace(",", "")), current_supply_count=int(numbers[2].replace(",", "")),
            official_supply_url=GAJEONG_SUPPLY_URL))
    # Read the current column, not the total stock or the already supplied
    # column. A printed dwelling code contains multiple physical subtypes.
    table_page = next((p for p in pages if p["page"] == 3), None)
    if table_page:
        for line in table_page["text"].splitlines():
            text = re.sub(r"\s+", " ", line).strip()
            match = re.search(r"\b(\d{2}\.\d{4}[A-Z])\b.{0,170}?\s(\d+)\s+(?:\d+|-)\s+(\d+)\s+(\d+)\s+(?:\d+|-)\s*$", text)
            if match:
                inventory.append({"supply_type": "일반공급", "unit_type": match[1], "supply_count": int(match[3]),
                    **{k: v for k, v in make("offered_supplies", evidence={"page": 3, "text": text}).items()
                       if k in {"verification", "evidence_url", "evidence_text", "evidence_page", "document_hash", "criterion_date"}}})
            # The merged 84A row carries the code and current inventory on the
            # next physical subtype line, alongside the expected occupation.
            merged = re.search(r"\b(\d{2}\.\d{4}[A-Z])\b.{0,170}?\s(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+\d+['’]?28\.07", text)
            if merged and not any(s["unit_type"] == merged[1] for s in inventory):
                inventory.append({"supply_type": "일반공급", "unit_type": merged[1], "supply_count": int(merged[4]),
                    **{k: v for k, v in make("offered_supplies", evidence={"page": 3, "text": text}).items()
                       if k in {"verification", "evidence_url", "evidence_text", "evidence_page", "document_hash", "criterion_date"}}})
    # Table extraction failure must not advertise a partial table as complete.
    if not total or sum(s["supply_count"] for s in inventory) != metadata[0]["current_supply_count"]:
        inventory = []

    duplicate = evidence(9, r"동일블록\s*내\s*중복신청이.{0,750}?후\s*접수분은\s*무효처리\s*합니다")
    instructions = []
    if duplicate:
        instructions.append({"label": "동일 블록 중복 신청·부부 예외", "detail": "동일 세대의 중복 신청으로 한 명이라도 당첨되면 모두 부적격입니다. 부부(예비신혼부부 제외)는 각각 신청할 수 있으며 중복 당첨 시 먼저 접수한 당첨만 유효합니다. 분 단위 접수 시각이 같으면 생년월일 기준 연장자의 당첨을 인정합니다.",
            "phase": "application", "evidence_page": 9, "evidence_text": duplicate["text"]})
    proof = evidence(11, r"당첨자\(예비입주자\)\s*제출서류.{0,170}")
    if proof:
        instructions.append({"label": "당첨 후 서류 제출·계약금 납부", "detail": "당첨자 서류 제출과 계약금·중도금·잔금 납부는 당첨 후 이행 절차입니다. 현재 신청 자격의 미확인 요건으로 세지 않습니다.", "phase": "post_selection", "evidence_page": 11, "evidence_text": proof["text"]})
    if instructions:
        metadata.append(make("application_instructions", effect="metadata", evidence=duplicate or proof,
            instructions=[{**item, "evidence_url": make("application_instructions")["evidence_url"], "document_hash": digest} for item in instructions]))
    return {"facts": facts, "metadata": metadata, "inventory": inventory, "original_announcement_date": "2026-04-15"}
