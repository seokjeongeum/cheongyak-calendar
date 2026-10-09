"""Bounded admission review of the exact current Hangang private-sale PDF.

The 62-page source was compared with the generic parser. Mandatory standard
paths and conditional unresolved alternatives have separate review records.
Payment, paperwork and duplicate-application instructions are never counted
as missing applicant facts.
"""
from __future__ import annotations

import re

HANGANG_HASH = "90a4d4e7e50b205ae45ee27cd7b3b50b5b8e1b3a65f19580f156336308cc1c34"
HANGANG_REVIEW_VERSION = "hangang-admission-2026-10-09-v2"
GENERAL = "일반공급"
SPECIALS = ("기관추천 특별공급", "다자녀가구 특별공급", "신혼부부 특별공급", "노부모부양 특별공급", "생애최초 특별공급", "신생아 특별공급")
BIRTH_TYPES = {SPECIALS[1], SPECIALS[2], SPECIALS[3], SPECIALS[5]}
INCOME_160 = (12054021, 14083523, 14923176, 15850021, 16776866, 17703710)
INCOME_140 = (10547268, 12323083, 13057779, 13868768, 14679757, 15490747)
DEPOSIT_TABLE = [
    {"max_area_sqm": area, "amounts_krw": dict(zip(("seoul_busan", "other_metropolitan", "other"), amounts))}
    for area, amounts in ((85, (3000000, 2500000, 2000000)), (102, (6000000, 4000000, 3000000)), (135, (10000000, 7000000, 4000000)), (None, (15000000, 10000000, 5000000)))
]


def hangang_admission(pages, *, digest, reviewed, rules, make):
    if digest != HANGANG_HASH or not reviewed or reviewed.get("title") != "쌍용 더 플래티넘 한강":
        return None
    source = {p["page"]: re.sub(r"\s+", " ", p["text"]).strip() for p in pages}
    if not set(range(1, 63)) <= source.keys():
        return None

    def e(page, pattern):
        match = re.search(pattern, source[page])
        return {"page": page, "quote": match.group(0)} if match else None

    overseas = e(3, r"출입국사실증명서\s*상\s*해외체류기간.{0,1200}?국내에\s*거주하고\s*있는\s*것으로\s*봅니다")
    illegal = e(3, r"주택법.{0,120}?제64조제1항.{0,180}?10년간\s*입주자로\s*선정될\s*수\s*없습니다")
    ineligible = e(3, r"부적격\s*당첨자로\s*판명된\s*경우.{0,420}?입주자로\s*선정될\s*수\s*없습니다")
    bank_used = e(4, r"당첨\s*된\s*청약통장은\s*계약여부와\s*관계없이\s*재사용이\s*불가합니다")
    general_account = e(21, r"2순위[^■]{0,350}?가입한\s*분")
    foreign = e(12, r"외국인은.{0,220}?특별공급\s*청약이\s*불가합니다")
    once = e(12, r"특별공급은\s*무주택세대구성원에게\s*한\s*차례에.{0,250}?횟수\s*제한\s*예외\)")
    account = e(12, r"기관추천\(장애인.{0,1800}?\[\s*청약예금의\s*예치금액\s*\]")
    waivers = e(1, r"소득\s*또는\s*자산기준[^■]{0,350}")
    if not all((overseas, illegal, ineligible, bank_used, general_account, foreign, once, account, waivers)):
        return None

    # Replace only the reviewed source's inaccurate or incomplete generic
    # facts. In particular, childbirth exemptions do not apply to institution
    # nomination or first-home supply.
    replaced = {"private_rank_months", "tax_years_min", "never_owned_home"}
    output = [r for r in rules if not (r.get("supply_type") in SPECIALS and r["kind"] in replaced)]
    for rule in output:
        if rule["kind"] == "homeless" and rule.get("supply_type") in {SPECIALS[0], SPECIALS[4]}:
            rule.pop("exceptions", None)

    output.append(make("domestic_residence", True, overseas_residence_equivalence=True, **e(4, r"국내에서\s*거주하는.{0,130}?외국인\s*포함")))
    output.append(make("overseas_residence", max_continuous_days=90,
        value_basis="continuous_days_including_reentry_within_7_days", currently_abroad_only=True,
        reentry_same_country=True, reentry_within_days=7, livelihood_exception=True,
        livelihood_exception_requires_family=True, **overseas))
    output.extend((make("application_restriction", False, restriction="resale_restriction_active", scope="applicant", restriction_years=10, **illegal),
                   make("application_restriction", False, restriction="ineligible_restriction_active", scope="applicant", restriction_months=12, **ineligible)))
    output.append(make("account_type", supply=GENERAL, allowed_values=["comprehensive", "deposit", "installment"],
        area_limit_for_installment=85, label="일반공급 2순위 이상 신청 가능한 통장", **general_account))
    def unused_account(supply):
        # A win after the notice still exhausts the account before applying.
        # Today/personal facts are evaluated in the browser, never on the API.
        return make("account_unused_after_winning", False, supply=supply,
            criterion_basis="application_date", criterion_date=None, original_announcement_date="2026-10-02",
            evaluation_mode="today_precheck", requires_maintained_until_application=True, **bank_used)
    output.append(unused_account(GENERAL))

    missing = {GENERAL: []}
    exempt_topics = {}
    for supply in (GENERAL, SPECIALS[0], SPECIALS[1], SPECIALS[3]):
        exempt_topics[supply] = [
            {"topic": "소득 기준", "status": "not_applicable", "required": False, "rule_ids": [], "evidence_page": 1, "evidence_text": waivers["quote"]},
            {"topic": "자산 기준", "status": "not_applicable", "required": False, "rule_ids": [], "evidence_page": 1, "evidence_text": waivers["quote"]},
        ]
    exempt_topics[GENERAL].extend({"topic": topic, "status": "not_applicable", "required": False, "rule_ids": []}
        for topic in ("무주택 세대구성원", "특별공급 횟수 제한", "세대주", "재당첨 제한"))

    for supply in SPECIALS:
        output.append(make("citizenship", supply=supply, allowed_values=["korean"], **foreign))
        winning = make("special_winning", False, supply=supply, scope="household", label="세대의 특별공급 당첨 이력", **once)
        exception_label = ("배우자 혼인 전 당첨·혼인특례·출산특례의 1회 사용 조건" if supply == SPECIALS[2]
                           else "배우자 혼인 전 특별공급 당첨 예외" if supply == SPECIALS[4]
                           else "배우자 혼인 전 당첨·출산특례의 1회 사용 조건" if supply == SPECIALS[5]
                           else "출산특례의 1회 사용·기존주택 처분 조건" if supply in BIRTH_TYPES
                           else "제36조제1호·제8호의2의 특별공급 횟수 예외")
        winning["exceptions"] = [make("unparsed", supply=supply, label=exception_label, text=exception_label, **once)]
        output.append(winning)
        bank = [make("account_type", supply=supply, allowed_values=["comprehensive", "deposit", "installment"], area_limit_for_installment=85, **account),
                make("private_rank_months", 6 if supply in SPECIALS[:3] else 12, supply=supply, operator=">=", **account),
                make("deposit_min_krw", supply=supply, deposit_table=DEPOSIT_TABLE, value_basis="residence_region_and_exclusive_area", **e(12, r"\[\s*청약예금의\s*예치금액\s*\].{0,550}?500만원")),
                unused_account(supply)]
        if supply == SPECIALS[0]:
            bank_group = make("all", supply=supply, label="기관추천 통장 조건 또는 공식 면제", conditions=bank, **account)
            bank_group["exceptions"] = [make("unparsed", supply=supply, label="장애인·국가유공자·철거주택 소유자 통장 면제",
                text="기관의 확정·예비 추천과 장애인·국가유공자·도시재생 부지제공자의 통장 면제 대상 사실을 비교해야 합니다.", **account)]
            output.append(bank_group)
            nomination = make("recommendation", supply=supply, require_confirmed=True,
                allowed_reasons=["장애인", "국가유공자·보훈", "중소기업 장기근속", "장기복무 군인"],
                unsupported_reason_label="철거주택 소유자·도시재생 부지제공자 추천 분기",
                unsupported_reason_evidence_page=12, unsupported_reason_evidence_text=account["quote"],
                includes_reserve_nomination=True, **e(13, r"최초\s*입주자모집공고일\s*현재.{0,140}?추천\s*및\s*인정서류를\s*받으신\s*분"))
            output.append(nomination)
            missing[supply] = ["철거주택 소유자 추천 사유·통장 면제 및 특별공급 횟수 예외"]
        else:
            output.extend(bank)
            missing[supply] = [exception_label]

    elder = e(16, r"피부양자의\s*배우자도\s*무주택자이어야.{0,130}")
    if elder:
        output.extend((make("parent_owns_home", False, supply=SPECIALS[3], **elder),
                       make("parent_spouse_owns_home", False, supply=SPECIALS[3], **elder)))
    else:
        missing[SPECIALS[3]].append("부양 대상 부모·그 배우자의 별도 무주택 조건")

    first = SPECIALS[4]
    first_home = e(17, r"생애최초로\s*주택을\s*구입하는\s*분.{0,320}?혼인\s*전\s*처분한\s*이력은\s*배제합니다")
    never_owned = make("never_owned_home", True, supply=first, scope="household", exclude_spouse_pre_marriage_disposed=True, **first_home)
    never_owned["exceptions"] = [make("unparsed", supply=first, label="생애최초의 제53조 과거 주택 소유 예외",
        text="60세 이상 직계존속 등 제53조의 공식 소유 예외와 과거 소유 사실의 적용 범위를 대조해야 합니다. 원시 과거 소유 사실만으로 제외하지 않습니다.",
        **e(38, r"만60세\s*이상의\s*직계존속.{0,170}?특별공급\s*신청자\s*제외\)"))]
    output.append(never_owned)
    missing[first].append("생애최초의 제53조 과거 주택 소유 예외")
    output.append(make("first_home_tax_activity", True, supply=first, tax_years_min=5, recent_tax_months=12,
        includes_tax_exemption=True, tax_years_basis="separate_calendar_years_not_60_months", **e(18, r"입주자모집공고일\s*현재\s*근로자\s*또는\s*자영업자.{0,360}?납부의무액이\s*없는\s*경우를\s*포함")))
    output.append(make("first_home_family", True, supply=first, solo_max_area_sqm=60,
        include_adoption=True, include_pregnancy=True, unmarried_child_required=True,
        unmarried_applicant_child_same_register=True, non_solo_requires_ascendant=True,
        **e(17, r"아래\s*‘가’\s*또는\s*‘나’.{0,420}?1인\s*가구\(혼인\s*중이\s*아니면서\s*미혼인\s*자녀도\s*없는\s*분\)")))

    for supply, income_page, asset_page in ((first, 18, 19), (SPECIALS[5], 20, 21)):
        income = make("monthly_income_max_krw", supply=supply, min_household_size=3,
            household_size_basis="official_income_household", value_basis="household_monthly_income",
            income_table=[{"household_size": size, "max_krw": amount} for size, amount in zip(range(3, 9), INCOME_160)],
            extra_person_krw=926845, extra_person_base_krw=579278, extra_person_income_base_last_krw=11064819, income_percent=160,
            **e(income_page, r"160%\s*이하\s*12,054,021원.{0,180}?17,703,710원"))
        assets = make("real_estate_max_krw", 331000000, supply=supply, operator="<=", asset_basis="real_estate",
            household_scope="all_legal_household_members", **e(asset_page, r"부동산\s*3억3,100만원.{0,100}?이하"))
        financial = make("any", supply=supply, label="월평균소득 또는 부동산 기준", conditions=[income, assets],
            **e(income_page, r"3단계\s*추첨공급.{0,400}?3,100만원\s*이하인\s*분"))
        financial["exceptions"] = [make("unparsed", supply=supply, label="국민기초생활수급자의 세대 소득 면제",
            text="공급신청자의 국민기초생활수급자 사실을 확인하면 해당 세대의 소득 기준을 충족한 것으로 봅니다.",
            **e(31, r"공급신청자가\s*국민기초생활\s*수급자이면.{0,100}?간주"))]
        output.append(financial)
        missing[supply].append("국민기초생활수급자의 세대 소득 면제")

    missing[SPECIALS[2]].extend(("맞벌이 부부 각각의 140% 소득 상한",
                               "국민기초생활수급자의 세대 소득 면제"))
    # The single-income/ordinary low-income branch is useful without claiming
    # that the unmodelled dual-income or benefit-recipient branches are done.
    newlywed_income = make("monthly_income_max_krw", supply=SPECIALS[2], min_household_size=3,
        household_size_basis="official_income_household", value_basis="household_monthly_income",
        income_table=[{"household_size": size, "max_krw": amount} for size, amount in zip(range(3, 9), INCOME_140)],
        extra_person_krw=810989, extra_person_base_krw=579278, extra_person_income_base_last_krw=11064819, income_percent=140,
        **e(15, r"140%\s*이하\s*10,547,268원.{0,180}?15,490,747원"))
    newlywed_anchor = e(14, r"2단계\s*일반공급.{0,500}?3,100만원\s*이하인\s*분")
    dual_income = make("monthly_income_max_krw", supply=SPECIALS[2], min_household_size=3,
        household_size_basis="official_income_household", value_basis="household_monthly_income",
        income_table=[{"household_size": size, "max_krw": amount} for size, amount in zip(range(3, 9), INCOME_160)],
        extra_person_krw=926845, extra_person_base_krw=579278, extra_person_income_base_last_krw=11064819, income_percent=160,
        **e(15, r"160%\s*이하\s*12,054,021원.{0,180}?17,703,710원"))
    dual_branch = make("all", supply=SPECIALS[2], label="맞벌이 소득 분기", conditions=[
        make("dual_income", True, supply=SPECIALS[2], **newlywed_anchor), dual_income,
        make("unparsed", supply=SPECIALS[2], label="부부 각각의 140% 소득 상한", text="맞벌이 합산 160% 이하 경로의 부부 각각 140% 이하 소득을 대조해야 합니다.", **newlywed_anchor)], **newlywed_anchor)
    def above_income(rule):
        return make("monthly_income_max_krw", supply=SPECIALS[2], operator=">",
            **{key: rule[key] for key in ("min_household_size", "household_size_basis", "value_basis", "income_table", "extra_person_krw", "extra_person_base_krw", "extra_person_income_base_last_krw", "income_percent")},
            quote=rule["evidence_text"], page=rule["evidence_page"])
    lottery_income = make("any", supply=SPECIALS[2], label="소득 상한 초과 추첨 분기", conditions=[
        make("all", supply=SPECIALS[2], conditions=[make("dual_income", False, supply=SPECIALS[2], **newlywed_anchor), above_income(newlywed_income)], **newlywed_anchor),
        make("all", supply=SPECIALS[2], conditions=[make("dual_income", True, supply=SPECIALS[2], **newlywed_anchor), above_income(dual_income)], **newlywed_anchor)], **newlywed_anchor)
    lottery = make("all", supply=SPECIALS[2], label="소득 초과·부동산 기준 추첨 분기", conditions=[lottery_income,
        make("real_estate_max_krw", 331000000, supply=SPECIALS[2], operator="<=", asset_basis="real_estate", household_scope="all_legal_household_members",
             **e(16, r"3억3,100만.{0,450}?이하"))], **newlywed_anchor)
    newlywed_financial = make("any", supply=SPECIALS[2], label="월평균소득 또는 부동산 기준", conditions=[newlywed_income, dual_branch, lottery], **newlywed_anchor)
    newlywed_financial["exceptions"] = [make("unparsed", supply=SPECIALS[2], label="국민기초생활수급자의 세대 소득 면제",
        text="공급신청자의 국민기초생활수급자 사실을 확인하면 해당 세대의 소득 기준을 충족한 것으로 봅니다.",
        **e(31, r"공급신청자가\s*국민기초생활\s*수급자이면.{0,100}?간주"))]
    output.append(newlywed_financial)

    for rule in output:
        nested = [rule]
        while nested:
            item = nested.pop()
            nested.extend(item.get("conditions", []))
            if item["kind"] == "monthly_income_max_krw" and item.get("income_percent"):
                footnote = e(item["evidence_page"], r"9인\s*이상\s*가구\s*소득기준.{0,260}?9인\s*이상\s*가구원수")
                item.update({"extra_person_evidence_text": footnote["quote"], "extra_person_evidence_page": footnote["page"]})

    for supply, income_page in ((SPECIALS[2], 16), (first, 19), (SPECIALS[5], 20)):
        scope_anchor = e(income_page, r"가구원수\s*산정\s*기준.{0,800}?소득산정\s*대상에서\s*제외")
        output.append(make("income_household_scope", supply=supply, effect="metadata",
            include_fetuses=True, ascendant_same_register_min_months=12, income_member_min_age=19,
            include_qualifying_minor_head=True, exclude_missing_cancelled_registration=True,
            income_year=2025, asset_household_scope="all_legal_household_members",
            **scope_anchor))

    instructions = [{"label": "신청 중복·부부 예외", "phase": "application", "detail": "같은 주택에 특별공급·일반공급 각 1건을 신청할 수 있습니다. 부부가 같은 발표일에 중복 당첨되면 접수시각이 빠른 건만 유효하며, 같은 분이면 연장자의 당첨이 유효합니다.", "evidence_page": 35},
                    {"label": "당첨 후 증빙·서류·납부", "phase": "post_selection", "detail": "자격 증빙 제출, 임신·입양 확인, 계약금·중도금·잔금 납부는 당첨 후 이행 절차입니다.", "evidence_page": 26}]
    for item in instructions:
        item["evidence_text"] = source[item["evidence_page"]][:900]
        provenance = make("application_instructions")
        item.update({"evidence_url": provenance["evidence_url"], "document_hash": digest})
    output.append(make("application_instructions", effect="metadata", instructions=instructions, **e(35, r"동일주택에\s*대하여\s*특별공급과\s*일반공급.{0,220}")))
    # Optional exemptions must not keep a fulfilled ordinary path unresolved.
    # Their unparsed condition nodes still return review if that alternative
    # becomes necessary. Remarriage is different: the previous same-spouse
    # period can tighten a seemingly passing current marriage period.
    conditional = {supply: [{"topic": topic, "status": "partial", "required": False,
                              "rule_ids": [], "phase": "conditional_admission", "reason": topic}
                             for topic in topics] for supply, topics in missing.items()}
    mandatory_missing = {supply: [] for supply in (GENERAL, *SPECIALS)}
    mandatory_missing[SPECIALS[2]] = ["동일 배우자와 재혼한 경우 이전 혼인기간 합산"]
    return {"rules": output, "missing_topics": mandatory_missing, "conditional_topics": conditional, "exempt_topics": exempt_topics,
            "review_version": HANGANG_REVIEW_VERSION, "reviewed_pages": list(range(1, 63))}
