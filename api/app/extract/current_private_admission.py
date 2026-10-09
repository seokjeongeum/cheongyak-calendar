"""Applicant clauses reviewed against three exact current private-sale files.

The source identities, page layouts and financial values are independent of
the project's address. Only these bytes receive this supplement. Unmodelled
conversion, prior-win and benefit alternatives stay explicit conditional
topics, and same-spouse remarriage stays a mandatory review item.
"""
from __future__ import annotations

import re

from .hangang_admission import DEPOSIT_TABLE, GENERAL, INCOME_140, INCOME_160, SPECIALS

REVIEW_VERSION = "current-private-admission-2026-10-09-v2"
SOURCE_LAYOUTS = {
    "b08df1475867c4c75e2d7f3d2d94e63be338975dc9ae5578638aa8dc9e56cf96": {
        "title": "용인 양지 서희스타힐스 하이뷰", "count": 58, "summary": 1, "active": 1,
        "overseas": 3, "restriction": 3, "ineligible": 3, "used": 4,
        "once": 9, "foreign": 9, "bank": 10, "nomination": 12, "general": 20, "domestic": 4,
        "first": 16, "first_income": 17, "first_asset": 17, "newborn": 18,
        "newborn_income": 19, "newborn_asset": 19, "newborn_scope": 19, "ownership": 23,
        "newlywed_income": 14, "newlywed_asset": 15, "newlywed_policy": 14, "newlywed_scope": 15,
        "reasons": ["장애인", "국가유공자·보훈"],
        "unsupported_reasons": ["장기복무 군인", "기타"],
    },
    "718d3a166be758bb8e4cae0617741b52c4d372050dcb399e5f8874583dafce01": {
        "title": "향남역 그로브 스위첸", "count": 94, "summary": 2, "active": 2,
        "overseas": 3, "restriction": 4, "ineligible": 4, "used": 5,
        "once": 12, "foreign": 13, "bank": 13, "nomination": 14, "general": 25, "domestic": 5,
        "first": 20, "first_income": 21, "first_asset": 22, "newborn": 22,
        "newborn_income": 23, "newborn_asset": 24, "newborn_scope": 24, "elder": 18, "ownership": 49, "benefits": 37,
        "newlywed_income": 17, "newlywed_asset": 18, "newlywed_policy": 16, "newlywed_scope": 17,
        "reasons": ["장애인", "국가유공자·보훈", "중소기업 장기근속", "장기복무 군인"],
        "unsupported_reasons": ["기타"],
    },
    "b5668bcd00f9606b110b21c9703fdce3994f5f690b43299fadeaf9ed2a73c61e": {
        "title": "향남역 그로브 스위첸", "count": 95, "summary": 2, "active": 2,
        "overseas": 4, "restriction": 4, "ineligible": 4, "ineligible_end": 5, "used": 6,
        "once": 13, "foreign": 13, "bank": 14, "nomination": 14, "general": 26, "domestic": 5,
        "first": 21, "first_income": 22, "first_asset": 23, "newborn": 23,
        "newborn_income": 24, "newborn_asset": 25, "newborn_scope": 24, "elder": 19, "ownership": 50, "benefits": 38,
        "newlywed_income": 18, "newlywed_asset": 19, "newlywed_policy": 17, "newlywed_scope": 18,
        "reasons": ["장애인", "국가유공자·보훈", "중소기업 장기근속", "장기복무 군인"],
        "unsupported_reasons": ["기타"],
    },
}


def current_private_admission(pages, *, digest, reviewed, rules, offered, make, _reviewed_layout=None, _review_version=None):
    # A separately gated, exact-source review can share the condition model
    # without borrowing another project's page layout or notice date.
    layout = _reviewed_layout or SOURCE_LAYOUTS.get(digest)
    if not layout or not reviewed or reviewed.get("title") != layout["title"]:
        return None
    source = {p["page"]: re.sub(r"\s+", " ", p["text"]).strip() for p in pages}
    if not set(range(1, layout["count"] + 1)) <= source.keys():
        return None

    def e(key, pattern):
        page = layout[key] if isinstance(key, str) else key
        body = " ".join(source[number] for number in range(page, layout.get(str(key) + "_end", page) + 1))
        match = re.search(pattern, body)
        return {"page": page, "quote": match.group(0)} if match else None

    active = e("active", r"입주자모집공고일\s*현재\s*입주자저축\s*순위요건을\s*만족하였으나.{0,150}?청약이\s*불가합니다")
    overseas = e("overseas", r"출입국사실증명서\s*(?:상\s*)?해외체류기간.{0,1300}?국내에\s*거주하고\s*있는\s*것으로\s*봅니다")
    illegal = e("restriction", r"주택법.{0,180}?제64조\s*제?1항.{0,220}?10년간\s*입주자로\s*선정될\s*수\s*없습니다")
    ineligible = e("ineligible", r"부적격\s*당\s*첨자로\s*판명된\s*경우.{0,550}?입주자로\s*선정될\s*수\s*없습니다")
    used = e("used", r"당첨\s*된\s*청약통장은\s*계약여부와\s*관계없이\s*재사용이\s*불가합니다")
    bank = e("bank", r"기관추천\(장애인.{0,2000}?\[\s*청약예금의\s*예치금액\s*\]")
    once = e("once", r"특별공급은\s*무주택세대구성원에게\s*한\s*차례에.{0,320}?횟수\s*제한\s*예외\)")
    foreign = e("foreign", r"외국인은.{0,250}?특별공급\s*청약이\s*불가합니다")
    nomination = e("nomination", r"최초\s*입주자모집공고일\s*현재\s*무주택세대구성원으로서.{0,150}?추천\s*및\s*인정서류를\s*받으신\s*분")
    general = e("general", r"2순위[^■]{0,350}?가입한\s*분")
    waivers = e("summary", r"소득\s*또는\s*자산기준\s*-\s*-\s*적용\s*-\s*적용\s*적용\s*-\s*-")
    domestic = e("domestic", r"국내에서\s*거주하는.{0,220}?외국인\s*포함")
    if not all((active, overseas, illegal, ineligible, used, bank, once, foreign, nomination, general, waivers, domestic)):
        return None

    replaced = {"private_rank_months", "deposit_min_krw", "tax_years_min", "never_owned_home"}
    output = [r for r in rules if not (r.get("supply_type") in SPECIALS and r["kind"] in replaced)]
    # First-home and institution have no childbirth home-ownership waiver.
    for r in output:
        if r["kind"] == "homeless" and r.get("supply_type") in {SPECIALS[0], SPECIALS[4]}:
            r.pop("exceptions", None)
    output.extend([
        make("domestic_residence", True, overseas_residence_equivalence=True, **domestic),
        make("overseas_residence", max_continuous_days=90, currently_abroad_only=True,
             value_basis="continuous_days_including_reentry_within_7_days", reentry_same_country=True,
             reentry_within_days=7, livelihood_exception=True, livelihood_exception_requires_family=True, **overseas),
        make("application_restriction", False, restriction="resale_restriction_active", scope="applicant", restriction_years=10, **illegal),
        make("application_restriction", False, restriction="ineligible_restriction_active", scope="applicant", restriction_months=12, **ineligible),
        make("account_type", supply=GENERAL, allowed_values=["comprehensive", "deposit", "installment"], area_limit_for_installment=85,
             label="일반공급 2순위 이상 신청 가능한 통장", **general),
    ])

    def current_bank(supply):
        fields = dict(supply=supply, criterion_basis="application_date", criterion_date=None,
                      original_announcement_date=reviewed["announcement_date"], evaluation_mode="today_precheck",
                      requires_maintained_until_application=True)
        return [make("account_unused_after_winning", False, **fields, **used),
                make("account_type", allowed_values=["comprehensive", "deposit", "installment"], area_limit_for_installment=85,
                     label="신청 시 유지 중인 청약통장", **fields, **active)]

    output.extend(current_bank(GENERAL))
    missing = {supply: [] for supply in offered}
    conditional = {supply: [] for supply in offered}
    exempt = {}
    # Reviewed ordinary bank facts do not certify unmodelled conversion dates.
    bank_conversion = "청약저축 전환·신청 주택규모 확대·지역 예치금 차액의 서로 다른 충족기한"
    for supply in offered:
        conditional[supply].append({"topic": bank_conversion, "status": "partial", "required": False,
                                    "phase": "conditional_admission", "rule_ids": [], "reason": bank_conversion})
        if supply in {GENERAL, SPECIALS[0], SPECIALS[1], SPECIALS[3]}:
            exempt[supply] = [{"topic": topic, "status": "not_applicable", "required": False, "rule_ids": [],
                               "evidence_page": waivers["page"], "evidence_text": waivers["quote"]}
                              for topic in ("소득 기준", "자산 기준")]
    for supply in offered:
        if supply not in SPECIALS:
            continue
        output.append(make("citizenship", supply=supply, allowed_values=["korean"], **foreign))
        winning = make("special_winning", False, supply=supply, scope="household", **once)
        waiver_label = ("배우자 혼인 전 당첨·혼인특례·출산특례의 1회 사용 조건" if supply == SPECIALS[2]
                       else "배우자 혼인 전 특별공급 당첨 예외" if supply == SPECIALS[4]
                       else "배우자 혼인 전 당첨·출산특례의 1회 사용 조건" if supply == SPECIALS[5]
                       else "제36조제1호·제8호의2의 특별공급 횟수 예외" if supply == SPECIALS[0]
                       else "출산특례의 1회 사용·기존주택 처분 조건")
        winning["exceptions"] = [make("unparsed", supply=supply, label=waiver_label, text=waiver_label, **once)]
        output.append(winning)
        conditional[supply].append({"topic": waiver_label, "status": "partial", "required": False,
                                   "phase": "conditional_admission", "rule_ids": [], "reason": waiver_label})
        requirements = [make("account_type", supply=supply, allowed_values=["comprehensive", "deposit", "installment"], area_limit_for_installment=85, **bank),
                        make("private_rank_months", 6 if supply in SPECIALS[:3] else 12, supply=supply, operator=">=", **bank),
                        make("deposit_min_krw", supply=supply, deposit_table=DEPOSIT_TABLE, require_as_of_date=True,
                             value_basis="announcement_balance", **e("bank", r"\[\s*청약예금의\s*예치금액\s*\].{0,650}?500만원")),
                        *current_bank(supply)]
        if supply == SPECIALS[0]:
            group = make("all", supply=supply, conditions=requirements, label="기관추천 통장 조건 또는 공식 면제", **bank)
            group["exceptions"] = [
                make("recommendation", supply=supply, label="장애인·국가유공자 통장 면제", require_confirmed=True,
                     includes_reserve_nomination=True, allowed_reasons=["장애인", "국가유공자·보훈"],
                     allowed_recommendation_reasons=["장애인", "국가유공자·보훈"], **bank),
                make("unparsed", supply=supply, label="철거주택 소유자·도시재생 부지제공자 통장 면제",
                     text="공식 추천과 철거주택 소유자·도시재생 부지제공자의 통장 면제 사실을 대조해야 합니다.",
                     allowed_recommendation_reasons=["철거주택 소유자", "도시재생 부지제공자"], **bank),
            ]
            output.append(group)
            output.append(make("recommendation", supply=supply, require_confirmed=True, includes_reserve_nomination=True,
                               allowed_reasons=layout["reasons"], unsupported_reason_label="공고에 열거된 장기복무 제대군인·철거주택 소유자의 별도 추천 분기",
                               unsupported_reasons=layout["unsupported_reasons"],
                               unsupported_reason_evidence_page=nomination["page"], unsupported_reason_evidence_text=source[nomination["page"]][:900], **nomination))
            conditional[supply].append({"topic": "장기복무 제대군인·철거주택 소유자의 추천·통장 면제 분기", "status": "partial", "required": False,
                                       "phase": "conditional_admission", "rule_ids": [], "reason": "장기복무 제대군인·철거주택 소유자의 추천·통장 면제 분기"})
        else:
            output.extend(requirements)

    if SPECIALS[3] in offered:
        elder = e("elder", r"피부양자의\s*배우자도\s*무주택자이어야.{0,130}")
        if elder:
            output.extend([make("parent_owns_home", False, supply=SPECIALS[3], **elder),
                           make("parent_spouse_owns_home", False, supply=SPECIALS[3], **elder)])
        else:
            missing[SPECIALS[3]].append("피부양자·다른 등본의 배우자를 포함하는 별도 무주택 기준")

    first = SPECIALS[4]
    family = e("first", r"아래\s*‘가’\s*또는\s*‘나’.{0,1500}?직계존속과\s*같은\s*세대를\s*구성하는\s*경우를\s*말함")
    past = e("first", r"생애최초로\s*주택을\s*구입하는\s*분.{0,450}?혼인\s*전\s*처분한\s*이력은\s*배제합니다")
    tax = e("first", r"입주자모집공고일\s*현재\s*근로자\s*또는\s*자영업자.{0,430}?납부\s*의무액이\s*없는\s*경우를\s*포함")
    if all((family, past, tax)):
        never_owned = make("never_owned_home", True, supply=first, scope="household", exclude_spouse_pre_marriage_disposed=True, **past)
        never_owned["exceptions"] = [make("unparsed", supply=first, label="생애최초의 제53조 과거 주택 소유 예외",
                                          text="법령상 소유 예외와 과거 소유 사실의 적용 범위를 대조해야 합니다.",
                                          **e("ownership", r"만\s*60세\s*이상의\s*직계존속.{0,200}?(?:특별공급\s*신청자|부양자\s*특별공급\s*신청자)\s*제외\)"))]
        output.extend([never_owned,
                       make("first_home_family", True, supply=first, solo_max_area_sqm=60, include_adoption=True, include_pregnancy=True,
                            unmarried_child_required=True, unmarried_applicant_child_same_register=True, non_solo_requires_ascendant=True, **family),
                       make("first_home_tax_activity", True, supply=first, tax_years_min=5, recent_tax_months=12,
                            includes_tax_exemption=True, tax_years_basis="separate_calendar_years_not_60_months", **tax)])
        conditional[first].append({"topic": "생애최초의 제53조 과거 주택 소유 예외", "status": "partial", "required": False,
                                   "phase": "conditional_admission", "rule_ids": [], "reason": "생애최초의 제53조 과거 주택 소유 예외"})
    else:
        missing[first].append("생애최초의 미혼·동일 등본 자녀·1인가구 면적 분기와 5년 소득세·최근 1년 납부 인정")

    for supply, prefix in ((first, "first"), (SPECIALS[5], "newborn")):
        if supply not in offered:
            continue
        income_anchor = e(prefix + "_income", r"160%\s*이하\s*~?12,054,021원.{0,220}?17,703,710원")
        asset_anchor = e(prefix + "_asset", r"부동산.{0,12}?3억\s*3,100(?:만원|이하만원).{0,140}")
        scope_anchor = e("newborn_scope" if prefix == "newborn" else prefix + "_income", r"가구원수\s*산정\s*기준.{0,1100}?소득산정\s*대상에서\s*제외")
        if income_anchor and asset_anchor and scope_anchor:
            income = make("monthly_income_max_krw", supply=supply, min_household_size=3, household_size_basis="official_income_household",
                          value_basis="household_monthly_income", income_table=[{"household_size": size, "max_krw": amount} for size, amount in zip(range(3, 9), INCOME_160)],
                          extra_person_krw=926845, extra_person_base_krw=579278, extra_person_income_base_last_krw=11064819, income_percent=160, **income_anchor)
            assets = make("real_estate_max_krw", 331000000, supply=supply, operator="<=", asset_basis="real_estate",
                          household_scope="all_legal_household_members", **asset_anchor)
            financial = make("any", supply=supply, label="월평균소득 또는 부동산 기준", conditions=[income, assets], **income_anchor)
            if "benefits" in layout:
                benefits = e("benefits", r"공급신청자가\s*국민기초생활\s*수급자이면.{0,140}?간주")
                if benefits:
                    financial["exceptions"] = [make("unparsed", supply=supply, label="국민기초생활수급자의 세대 소득 면제",
                        text="공급신청자의 국민기초생활수급자 사실이 있으면 세대 소득 기준을 충족한 것으로 봅니다.", **benefits)]
                    conditional[supply].append({"topic": "국민기초생활수급자의 세대 소득 면제", "status": "partial", "required": False,
                                               "phase": "conditional_admission", "rule_ids": [], "reason": "국민기초생활수급자의 세대 소득 면제"})
            output.append(financial)
            output.append(make("income_household_scope", supply=supply, effect="metadata", include_fetuses=True, ascendant_same_register_min_months=12,
                               income_member_min_age=19, include_qualifying_minor_head=True, exclude_missing_cancelled_registration=True,
                               income_year=2025, asset_household_scope="all_legal_household_members", **scope_anchor))
        else:
            missing[supply].append("가구원별 160% 월평균소득 또는 3억3,100만원 부동산 기준·산정 가구 범위")

    if SPECIALS[2] in missing:
        supply = SPECIALS[2]
        missing[supply] = ["동일 배우자와 재혼한 경우 이전 혼인기간 합산"]
        policy = e("newlywed_policy", r"2단계\s*일반공급.{0,750}?3,100만원\s*이하인\s*분")
        income_140 = e("newlywed_income", r"140%\s*이하\s*~?10,547,268원.{0,220}?15,490,747원")
        income_160 = e("newlywed_income", r"160%\s*이하\s*~?12,054,021원.{0,220}?17,703,710원")
        asset = e("newlywed_asset", r"부동산.{0,12}?3억\s*3,100(?:만원|이하만원).{0,140}")
        household = e("newlywed_scope", r"가구원수\s*산정\s*기준.{0,1100}?소득산정\s*대상에서\s*제외")
        if all((policy, income_140, income_160, asset, household)):
            def income(percent, table, anchor, operator="<="):
                return make("monthly_income_max_krw", supply=supply, operator=operator, min_household_size=3,
                            household_size_basis="official_income_household", value_basis="household_monthly_income",
                            income_table=[{"household_size": size, "max_krw": amount} for size, amount in zip(range(3, 9), table)],
                            extra_person_krw=810989 if percent == 140 else 926845, extra_person_base_krw=579278,
                            extra_person_income_base_last_krw=11064819, income_percent=percent, **anchor)
            dual = make("all", supply=supply, label="맞벌이 소득 분기", conditions=[
                make("dual_income", True, supply=supply, **policy), income(160, INCOME_160, income_160),
                make("unparsed", supply=supply, label="부부 각각의 140% 소득 상한",
                     text="맞벌이 합산 160% 이하 경로는 부부 각각의 소득도 140% 이하여야 합니다.", **policy)], **policy)
            above = make("any", supply=supply, label="소득 상한 초과 추첨 분기", conditions=[
                make("all", supply=supply, conditions=[make("dual_income", False, supply=supply, **policy), income(140, INCOME_140, income_140, ">")], **policy),
                make("all", supply=supply, conditions=[make("dual_income", True, supply=supply, **policy), income(160, INCOME_160, income_160, ">")], **policy)], **policy)
            lottery = make("all", supply=supply, label="소득 초과·부동산 기준 추첨 분기", conditions=[above,
                make("real_estate_max_krw", 331000000, supply=supply, operator="<=", asset_basis="real_estate",
                     household_scope="all_legal_household_members", **asset)], **policy)
            group = make("any", supply=supply, label="월평균소득 또는 부동산 기준",
                         conditions=[income(140, INCOME_140, income_140), dual, lottery], **policy)
            if "benefits" in layout:
                benefits = e("benefits", r"공급신청자가\s*국민기초생활\s*수급자이면.{0,140}?간주")
                if benefits:
                    group["exceptions"] = [make("unparsed", supply=supply, label="국민기초생활수급자의 세대 소득 면제",
                                                text="공급신청자의 국민기초생활수급자 사실이 있으면 세대 소득 기준을 충족한 것으로 봅니다.", **benefits)]
            output.extend([group, make("income_household_scope", supply=supply, effect="metadata", include_fetuses=True,
                                      ascendant_same_register_min_months=12, income_member_min_age=19, include_qualifying_minor_head=True,
                                      exclude_missing_cancelled_registration=True, income_year=2025, asset_household_scope="all_legal_household_members", **household)])
            conditional[supply].append({"topic": "맞벌이 부부 각각의 140% 소득 상한", "status": "partial", "required": False,
                                       "phase": "conditional_admission", "rule_ids": [], "reason": "맞벌이 부부 각각의 140% 소득 상한"})
        else:
            missing[supply].append("신혼부부의 외벌이 140%·맞벌이 160% 및 부부 각각 140%·소득 초과 추첨 부동산 분기")
    # Payment, paperwork, allocation and optional conversion/waiver paths do
    # not block the reviewed standard branch. Unparsed alternative nodes still
    # require review if an ordinary mandatory condition is not satisfied.
    return {"rules": output, "missing_topics": missing, "conditional_topics": conditional, "exempt_topics": exempt,
            "review_version": _review_version or REVIEW_VERSION, "reviewed_pages": sorted({v for k, v in layout.items() if k != "count" and isinstance(v, int)})}
