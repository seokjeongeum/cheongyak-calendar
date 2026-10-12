"""Document-shaped admission review without notice identities or fixed pages.

Discovery binds each condition to this document's applicant section. Financial
amounts and deposit columns come from the printed tables; unsupported clauses
and alternative exemptions remain explicit, never inferred from a title.
"""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP

GENERAL = "일반공급"
SPECIALS = ("기관추천 특별공급", "다자녀가구 특별공급", "신혼부부 특별공급", "노부모부양 특별공급", "생애최초 특별공급", "신생아 특별공급")
REVIEW_VERSION = "generic-admission-2026-10-10-v1"

def _condition_model(pages, *, digest, reviewed, rules, offered, make, layout, values):
    source = {p["page"]: re.sub(r"\s+", " ", p["text"]).strip() for p in pages}
    def make_condition(kind, value=None, **kwargs):
        return make(kind, value, **kwargs)

    e = layout["finder"]

    active = e("active", r"입주자모집공고일\s*현재\s*입주자저축\s*순위요건을\s*만족하였으나.{0,150}?청약이\s*불가합니다")
    overseas = e("overseas", r"출입국사실증명서\s*(?:상\s*)?해외체류기간.{0,1300}?국내에\s*거주하고\s*있는\s*것으로\s*봅니다")
    illegal = e("restriction", r"주택법.{0,180}?제64조\s*제?1항.{0,220}?\d+년간\s*입주자로\s*선정될\s*수\s*없습니다")
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
        make("overseas_residence", max_continuous_days=values["overseas_days"], currently_abroad_only=True,
             value_basis=f"continuous_days_including_reentry_within_{values['reentry_days']}_days", reentry_same_country=True,
             reentry_within_days=values["reentry_days"], livelihood_exception=True, livelihood_exception_requires_family=True, **overseas),
        make("application_restriction", False, restriction="resale_restriction_active", scope="applicant", restriction_years=values["illegal_years"], **illegal),
        make("application_restriction", False, restriction="ineligible_restriction_active", scope="applicant", restriction_months=values["ineligible_months"], **ineligible),
        make("account_type", supply=GENERAL, allowed_values=values["general_accounts"], **values["general_account_fields"],
             label="일반공급 2순위 이상 신청 가능한 통장", **general),
    ])

    def current_bank(supply):
        fields = dict(supply=supply, criterion_basis="application_date", criterion_date=None,
                      original_announcement_date=reviewed["announcement_date"], evaluation_mode="today_precheck",
                      requires_maintained_until_application=True)
        return [make("account_unused_after_winning", False, **fields, **used),
                make("account_type", allowed_values=values["special_accounts"] if supply != GENERAL else values["general_accounts"], **values["account_fields"],
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
        if values["income_applies"].get(supply) is False:
            exempt[supply] = [{"topic": topic, "status": "not_applicable", "required": False, "rule_ids": [],
                               "evidence_page": waivers["page"], "evidence_text": waivers["quote"], "waived_rule_kind": "monthly_income_max_krw" if topic == "소득 기준" else "real_estate_max_krw"}
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
        requirements = [make("account_type", supply=supply, allowed_values=values["special_accounts"], **values["account_fields"], **bank),
                        make("private_rank_months", values["months"][supply], supply=supply, operator=">=", **bank),
                        make("deposit_min_krw", supply=supply, deposit_table=values["deposit_table"], require_as_of_date=True,
                             value_basis="announcement_balance", **values["deposit_evidence"]),
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
                               allowed_reasons=layout["reasons"], unsupported_reason_label="공고에 열거된 별도 추천 대상·통장 면제 분기",
                               unsupported_reasons=layout["unsupported_reasons"],
                               unsupported_reason_evidence_page=layout["unsupported_evidence"]["page"], unsupported_reason_evidence_text=layout["unsupported_evidence"]["quote"], **nomination))
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
    if all((family, past, tax, values["tax_years"], values["recent_tax_months"], values["solo_max_area"])):
        never_owned = make("never_owned_home", True, supply=first, scope="household", exclude_spouse_pre_marriage_disposed=True, supersedes_rule_kinds=["never_owned_home"], **past)
        never_owned["exceptions"] = [make("unparsed", supply=first, label="생애최초의 제53조 과거 주택 소유 예외",
                                          text="법령상 소유 예외와 과거 소유 사실의 적용 범위를 대조해야 합니다.",
                                          **(e("ownership", r"만\s*60세\s*이상의\s*직계존속.{0,200}?(?:특별공급\s*신청자|부양자\s*특별공급\s*신청자)\s*제외\)") or past))]
        output.extend([never_owned,
                       make("first_home_family", True, supply=first, solo_max_area_sqm=values["solo_max_area"], include_adoption=True, include_pregnancy=True,
                            unmarried_child_required=True, unmarried_applicant_child_same_register=True, non_solo_requires_ascendant=True, **family),
                       make("first_home_tax_activity", True, supply=first, tax_years_min=values["tax_years"], recent_tax_months=values["recent_tax_months"], supersedes_rule_kinds=["tax_years_min"],
                            includes_tax_exemption=True, tax_years_basis="separate_calendar_years_not_60_months", **tax)])
        conditional.setdefault(first, []).append({"topic": "생애최초의 제53조 과거 주택 소유 예외", "status": "partial", "required": False,
                                   "phase": "conditional_admission", "rule_ids": [], "reason": "생애최초의 제53조 과거 주택 소유 예외"})
    else:
        # The ownership paragraph was acquired independently of the family,
        # tax and financial branches; an unrelated missing paragraph must not
        # erase its already source-bound exemptions.
        output.extend(rule for rule in rules if rule["kind"] == "never_owned_home" and rule.get("supply_type") == first)
        missing.setdefault(first, []).append("생애최초의 미혼·동일 등본 자녀·1인가구 면적 분기와 소득세·최근 납부 인정기간")

    for supply, prefix in ((first, "first"), (SPECIALS[5], "newborn")):
        if supply not in offered or values["income_applies"].get(supply) is False:
            continue
        financial_values = values["financial"].get(supply, {})
        income_anchor = financial_values.get("income_evidence")
        asset_anchor = financial_values.get("asset_evidence")
        scope_anchor = e("newborn_scope" if prefix == "newborn" else prefix + "_income", r"가구원수\s*산정\s*기준.{0,1100}?소득산정\s*대상에서\s*제외")
        if income_anchor and asset_anchor and scope_anchor and financial_values.get("income_ascendant_months") and financial_values.get("income_member_age"):
            income = make("monthly_income_max_krw", supply=supply, min_household_size=financial_values["min_household_size"], household_size_basis="official_income_household",
                          value_basis="household_monthly_income", income_table=financial_values["income_table"],
                          **financial_values["extension"], income_percent=financial_values["percent"], **income_anchor)
            assets = make("real_estate_max_krw", financial_values["asset_max_krw"], supply=supply, operator="<=", asset_basis="real_estate",
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
            output.append(make("income_household_scope", supply=supply, effect="metadata", include_fetuses=True, ascendant_same_register_min_months=financial_values["income_ascendant_months"],
                               income_member_min_age=financial_values["income_member_age"], include_qualifying_minor_head=True, exclude_missing_cancelled_registration=True,
                               income_year=financial_values["year"], asset_household_scope="all_legal_household_members", **scope_anchor))
        else:
            missing[supply].append("현재 공고의 가구원별 월평균소득·부동산 기준표 및 산정 가구 범위")

    if SPECIALS[2] in missing and values["income_applies"].get(SPECIALS[2]) is not False:
        supply = SPECIALS[2]
        missing[supply] = ["동일 배우자와 재혼한 경우 이전 혼인기간 합산"]
        financial_values = values["financial"].get(supply, {})
        policy = financial_values.get("policy_evidence")
        income_140 = financial_values.get("single_evidence")
        income_160 = financial_values.get("dual_evidence")
        asset = financial_values.get("asset_evidence")
        household = e("newlywed_scope", r"가구원수\s*산정\s*기준.{0,1100}?소득산정\s*대상에서\s*제외")
        if all((policy, income_140, income_160, asset, household, financial_values.get("income_ascendant_months"), financial_values.get("income_member_age"))):
            def income(percent, table, anchor, operator="<="):
                return make("monthly_income_max_krw", supply=supply, operator=operator, min_household_size=financial_values["min_household_size"],
                            household_size_basis="official_income_household", value_basis="household_monthly_income",
                            income_table=table, **financial_values["extensions"][percent], income_percent=percent, **anchor)
            dual = make("all", supply=supply, label="맞벌이 소득 분기", conditions=[
                make("dual_income", True, supply=supply, **policy), income(financial_values["dual_percent"], financial_values["dual_table"], income_160),
                make("unparsed", supply=supply, label=financial_values["spouse_limit_label"],
                     text=financial_values["spouse_limit_text"], **policy)], **policy)
            above = make("any", supply=supply, label="소득 상한 초과 추첨 분기", conditions=[
                make("all", supply=supply, conditions=[make("dual_income", False, supply=supply, **policy), income(financial_values["single_percent"], financial_values["single_table"], income_140, ">")], **policy),
                make("all", supply=supply, conditions=[make("dual_income", True, supply=supply, **policy), income(financial_values["dual_percent"], financial_values["dual_table"], income_160, ">")], **policy)], **policy)
            lottery = make("all", supply=supply, label="소득 초과·부동산 기준 추첨 분기", conditions=[above,
                make("real_estate_max_krw", financial_values["asset_max_krw"], supply=supply, operator="<=", asset_basis="real_estate",
                     household_scope="all_legal_household_members", **asset)], **policy)
            group = make("any", supply=supply, label="월평균소득 또는 부동산 기준",
                         conditions=[income(financial_values["single_percent"], financial_values["single_table"], income_140), dual, lottery], **policy)
            if "benefits" in layout:
                benefits = e("benefits", r"공급신청자가\s*국민기초생활\s*수급자이면.{0,140}?간주")
                if benefits:
                    group["exceptions"] = [make("unparsed", supply=supply, label="국민기초생활수급자의 세대 소득 면제",
                                                text="공급신청자의 국민기초생활수급자 사실이 있으면 세대 소득 기준을 충족한 것으로 봅니다.", **benefits)]
            output.extend([group, make("income_household_scope", supply=supply, effect="metadata", include_fetuses=True,
                                      ascendant_same_register_min_months=financial_values["income_ascendant_months"], income_member_min_age=financial_values["income_member_age"], include_qualifying_minor_head=True,
                                      exclude_missing_cancelled_registration=True, income_year=financial_values["year"], asset_household_scope="all_legal_household_members", **household)])
            conditional[supply].append({"topic": financial_values["spouse_limit_label"], "status": "partial", "required": False,
                                       "phase": "conditional_admission", "rule_ids": [], "reason": financial_values["spouse_limit_label"]})
        else:
            missing[supply].append("현재 공고의 외벌이·맞벌이·부부 개별 소득 상한 및 추첨 부동산 분기")
    # Payment, paperwork, allocation and optional conversion/waiver paths do
    # not block the reviewed standard branch. Unparsed alternative nodes still
    # require review if an ordinary mandatory condition is not satisfied.
    return {"rules": output, "missing_topics": missing, "conditional_topics": conditional, "exempt_topics": exempt,
            "review_version": REVIEW_VERSION, "reviewed_pages": sorted(source), "completion_basis": "document_structure_reviewed_standard_branch"}


def _normal(text):
    return re.sub(r"\s+", " ", text).strip()


def _find(pages, pattern):
    """Match ordinary paragraph continuations and retain its actual start page."""
    spans = []
    text = ""
    for page in pages:
        body = _normal(page["text"])
        spans.append((len(text), len(text) + len(body), page["page"]))
        text += body + " "
    match = re.search(pattern, text)
    if not match:
        return None
    page = next(number for start, end, number in spans if start <= match.start() <= end)
    return {"page": page, "quote": match.group(0)}


def _deposit_values(pages):
    candidates = []
    incomplete = False
    for page in pages:
        compact = re.sub(r"\s+", "", page["text"])
        marker = compact.find("청약예금의예치금액")
        if marker < 0:
            continue
        body = compact[marker:marker + 1600]
        groups = {"seoul_busan": "특별시및부산광역시", "other_metropolitan": "그밖의광역시", "other": "특별시및광역시를제외한지역"}
        positions = {key: body.find(label) for key, label in groups.items()}
        if min(positions.values()) < 0:
            continue
        order = sorted(positions, key=positions.get)
        evidence = _find([page], r"\[\s*청약예금의\s*예치금액\s*\].{0,1000}?모든\s*면적\s*[\d,]+만원\s*[\d,]+만원\s*[\d,]+만원")
        if not evidence:
            if re.search(r"전용면적\d+(?:\.\d+)?[㎡m²]|모든면적", body):
                incomplete = True
            continue
        body = re.sub(r"\s+", "", evidence["quote"])
        printed_limits = [float(match[1]) if match[1] else None for match in re.finditer(
            r"(?:전용면적(?:이하)?(\d+(?:\.\d+)?)[㎡m²]+(?:이하)?|(모든면적))", body)]
        rows = []
        for match in re.finditer(r"(?:전용면적(?:이하)?(\d+(?:\.\d+)?)[㎡m²]+(?:이하)?|(모든면적))([\d,]+)만원([\d,]+)만원([\d,]+)만원", body):
            rows.append({"max_area_sqm": float(match[1]) if match[1] else None,
                         "amounts_krw": dict(zip(order, [int(v.replace(',', '')) * 10000 for v in match.groups()[2:]]))})
        if len(rows) < 2 or rows[-1]["max_area_sqm"] is not None:
            incomplete = True
            continue
        # A readable larger-area row cannot replace an unreadable smaller
        # row. Compare every printed boundary without fixing legal defaults.
        if [row["max_area_sqm"] for row in rows] != printed_limits:
            incomplete = True
            continue
        if any(row["max_area_sqm"] is None for row in rows[:-1]) or any(rows[i]["max_area_sqm"] >= rows[i + 1]["max_area_sqm"] for i in range(len(rows) - 2)):
            incomplete = True
            continue
        candidates.append((rows, evidence))
    if incomplete or not candidates or any(rows != candidates[0][0] for rows, _ in candidates):
        return None, None
    return candidates[0]


def _income_rows(pages):
    """Accept printed household headers + complete rows, reject contradictions."""
    rows = {}
    year = None
    sizes = None
    for page in pages:
        body = _normal(page["text"])
        header = re.search(r"(\d+)인\s*이하\s*((?:\d+인\s*){2,})", body)
        if not header:
            continue
        current_sizes = [int(header[1]), *(int(v) for v in re.findall(r"(\d+)인", header[2]))]
        if current_sizes != list(range(current_sizes[0], current_sizes[-1] + 1)):
            return {}, None, None
        if sizes is not None and sizes != current_sizes:
            return {}, None, None
        sizes = current_sizes
        year_match = re.search(r"(20\d{2})년도\s*도시근로자", body)
        if year_match:
            if year is not None and year != int(year_match[1]):
                return {}, None, None
            year = int(year_match[1])
        amount = r"~?([\d,]+)원"
        pattern = r"(\d+)%\s*이하\s*" + r"\s*".join([amount] * len(sizes))
        for match in re.finditer(pattern, body):
            percent = int(match[1])
            table = [{"household_size": size, "max_krw": int(value.replace(',', ''))} for size, value in zip(sizes, match.groups()[1:])]
            if any(table[i]["max_krw"] > table[i + 1]["max_krw"] for i in range(len(table) - 1)) or min(x['max_krw'] for x in table) <= 0:
                return {}, None, None
            if percent in rows and rows[percent]["table"] != table:
                return {}, None, None
            rows.setdefault(percent, {"table": table, "evidence": {"page": page["page"], "quote": match.group(0)}})
    return rows, year, sizes


def _income_extension(pages, *, percent, rows):
    issue = {'extra_person_formula_verified': False,
             'extra_person_formula_issue': '소득표를 초과하는 가구원 수의 공식 추가 인원 산식 미확보'}
    pattern = r"(\d+)인\s*이상\s*가구\s*소득기준.{0,240}?1인당\s*평균소득\s*\(([\d,]+)\).{0,120}?(?:N\s*[-−]\s*(\d+))"
    text = _normal(' '.join(page['text'] for page in pages))
    formulas = {(int(match[1]), int(match[2].replace(',', '')), int(match[3])) for match in re.finditer(pattern, text)}
    if len(formulas) != 1 or not rows or percent not in rows or any(pct <= 0 for pct in rows):
        return issue
    start, basis, offset = next(iter(formulas))
    last_sizes = {row['table'][-1]['household_size'] for row in rows.values() if row.get('table')}
    if len(last_sizes) != 1 or offset != next(iter(last_sizes)) or start != offset + 1 or basis <= 0:
        return {**issue, 'extra_person_formula_issue': '추가 인원 산식의 시작 가구원 수·차감 인원과 소득표 마지막 행이 다릅니다.'}
    evidence = _find(pages, pattern)
    base_row = rows.get(100)
    # Some tables omit the 100% row. In that case infer its printed last-person
    # base only when all published percentages agree under official rounding.
    if base_row:
        base = base_row["table"][-1]["max_krw"]
    else:
        estimates = [Decimal(row['table'][-1]['max_krw']) * 100 / Decimal(pct) for pct, row in rows.items()]
        lower = max(value - Decimal(100) / pct / 2 for value, pct in zip(estimates, rows))
        upper = min(value + Decimal(100) / pct / 2 for value, pct in zip(estimates, rows))
        integers = [n for n in range(int(lower) - 1, int(upper) + 2)
                    if all(int((Decimal(n) * pct / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)) == row['table'][-1]['max_krw']
                           for pct, row in rows.items())]
        if len(integers) != 1:
            return {**issue, 'extra_person_formula_issue': '소득표의 비율별 마지막 행에서 공식 기준소득을 하나로 확정할 수 없습니다.'}
        base = integers[0]
    if any(int((Decimal(base) * pct / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)) != row['table'][-1]['max_krw']
           for pct, row in rows.items()):
        return {**issue, 'extra_person_formula_issue': '소득표의 비율별 마지막 행이 공식 기준소득과 일치하지 않습니다.'}
    return {"extra_person_krw": int((Decimal(basis) * percent / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)),
            "extra_person_base_krw": basis, "extra_person_income_base_last_krw": base,
            "extra_person_evidence_text": evidence['quote'], "extra_person_evidence_page": evidence['page'],
            "extra_person_formula_verified": True}


def _asset_value(pages):
    evidence = []
    for page in pages:
        for match in re.finditer(r"부동산(?:가\s*액)?\s*(?:\(건물\+토지\))?\s*(\d+)억\s*([\d,]+)만원.{0,100}?이하", _normal(page['text'])):
            evidence.append((int(match[1]) * 100000000 + int(match[2].replace(',', '')) * 10000,
                             {'page': page['page'], 'quote': match[0]}))
    if not evidence or len({value for value, _ in evidence}) != 1:
        return None, None
    return evidence[-1]


def _financial_values(section, supply):
    pages = _section_pages(section)
    rows, year, sizes = _income_rows(pages)
    asset, asset_evidence = _asset_value(pages)
    body = _normal(' '.join(page['text'] for page in pages))
    if not rows or year is None or not asset_evidence:
        return {}
    ascendant = _unique_int(r'최근\s*(\d+)년\s*이상\s*계속하여\s*공급신청자', body)
    member_age = _unique_int(r'가구원\s*중\s*만\s*(\d+)세\s*이상인\s*성년자', body)
    scope_values = {'income_ascendant_months': ascendant * 12 if ascendant else None, 'income_member_age': member_age}
    if supply == SPECIALS[2]:
        policy = _find(pages, r"2단계\s*일반공급.{0,700}?3단계\s*추첨공급.{0,450}?부동산가\s*액.{0,120}?\d+억\s*[\d,]+만원\s*이하인\s*분")
        if not policy:
            return {}
        before_lottery = policy['quote'].split('3단계')[0]
        percentages = re.findall(r"(\d+)%\s*이하", before_lottery)
        if len(percentages) < 3:
            return {}
        single, dual, spouse = map(int, percentages[:3])
        if single not in rows or dual not in rows:
            return {}
        spouse_one = bool(re.search(r"부부\s*중\s*1인(?:의)?\s*소득", policy['quote']))
        label = f"부부 중 1인의 {spouse}% 소득 상한" if spouse_one else f"부부 각각의 {spouse}% 소득 상한"
        return {'single_percent': single, 'dual_percent': dual, 'single_table': rows[single]['table'], 'dual_table': rows[dual]['table'],
                'single_evidence': rows[single]['evidence'], 'dual_evidence': rows[dual]['evidence'], 'asset_max_krw': asset,
                'asset_evidence': asset_evidence, 'policy_evidence': policy, 'year': year, 'min_household_size': sizes[0],
                'spouse_limit_label': label, 'spouse_limit_text': f"맞벌이 합산 {dual}% 이하 경로는 {label}도 충족해야 합니다.",
                **scope_values, 'extensions': {p: _income_extension(pages, percent=p, rows=rows) for p in (single, dual)}}
    policy = _find(pages, r"2단계\s*일반공급.{0,600}?3단계\s*추첨공급.{0,400}?부동산가\s*액.{0,120}?\d+억\s*[\d,]+만원\s*이하인\s*분")
    if not policy:
        return {}
    amounts = re.findall(r"(\d+)%\s*이하", policy['quote'].split('3단계')[0])
    if not amounts:
        return {}
    percent = int(amounts[-1])
    if percent not in rows:
        return {}
    return {'percent': percent, 'income_table': rows[percent]['table'], 'income_evidence': rows[percent]['evidence'],
            'asset_max_krw': asset, 'asset_evidence': asset_evidence, 'policy_evidence': policy, 'year': year,
            'min_household_size': sizes[0], **scope_values, 'extension': _income_extension(pages, percent=percent, rows=rows)}


def _section_pages(section):
    result = {}
    for line in (section or {}).get('lines', []):
        result.setdefault(line['page'], []).append(line['text'])
    return [{'page': page, 'text': '\n'.join(lines)} for page, lines in result.items()]


def _first_home_ownership(pages, applicant_pages, rules, make):
    """Keep a source-backed ownership comparison when another topic is missing.

    A missing bank table or tax paragraph prevents whole-branch certification,
    but does not invalidate the separately acquired first-home ownership clause.
    Scope is the actual applicant paragraph, not a summary or a project title.
    """
    first = SPECIALS[4]
    past = _find(applicant_pages, r"생애최초로\s*주택을\s*구입하는\s*분\s*[-–]?\s*모든\s*세대구성원이\s*과거\s*주택을\s*소유한\s*사실이\s*없는\s*경우를\s*말함")
    if not past:
        return rules
    spouse = _find(applicant_pages, r"청약신청자의\s*배우자가\s*혼인\s*전\s*주택을\s*소유하였다가\s*혼인\s*전\s*처분한\s*이력은\s*배제합니다")
    ancestry = _find(pages, r"만\s*60세\s*이상의\s*직계존속.{0,180}?주택\s*또는\s*분양권등을\s*소유하고\s*있는\s*경우\s*\(단,\s*노부모(?:부양자|부양)?\s*특별공급\s*신청자\s*제외\)")
    fields = dict(supply=first, scope="household", supersedes_rule_kinds=["never_owned_home"], **past)
    if spouse:
        fields.update(exclude_spouse_pre_marriage_disposed=True,
                      spouse_exception_evidence_page=spouse["page"], spouse_exception_evidence_text=spouse["quote"])
    ownership = make("never_owned_home", True, **fields)
    ownership["exceptions"] = [make("unparsed", supply=first, label="생애최초의 제53조 과거 주택 소유 예외",
        text="법령상 소유 예외와 과거 소유 사실의 적용 범위를 대조해야 합니다.", **(ancestry or past))]
    return [*[rule for rule in rules if not (rule["kind"] == "never_owned_home" and rule.get("supply_type") == first)], ownership]


def generic_private_admission(pages, *, digest, payload, rules, offered, sections, make):
    """Discover and review a supported document structure, independent of IDs."""
    sections_by_supply = {}
    for section in sections:
        supply = section['supply_type']
        # Duplicated applicant headings with incompatible requirements are
        # ambiguous; a contents listing has already been excluded upstream.
        if supply in sections_by_supply:
            return None
        sections_by_supply[supply] = section
    if not offered or not set(offered) <= {GENERAL, *SPECIALS}:
        return None
    scoped = {supply: _section_pages(section) for supply, section in sections_by_supply.items()}
    if SPECIALS[4] in offered:
        rules = _first_home_ownership(pages, scoped.get(SPECIALS[4], []), rules, make)
    income_applies, summary_anchor = _summary_applies(pages)
    def e(key, pattern):
        if key == "summary":
            return summary_anchor
        section_key = {'first': SPECIALS[4], 'first_income': SPECIALS[4], 'first_asset': SPECIALS[4],
                       'newborn': SPECIALS[5], 'newborn_income': SPECIALS[5], 'newborn_asset': SPECIALS[5], 'newborn_scope': SPECIALS[5],
                       'newlywed_income': SPECIALS[2], 'newlywed_asset': SPECIALS[2], 'newlywed_policy': SPECIALS[2], 'newlywed_scope': SPECIALS[2],
                       'elder': SPECIALS[3], 'nomination': SPECIALS[0], 'general': GENERAL}
        return _find(scoped.get(section_key[key], []) if key in section_key else pages, pattern)
    common = {
        'active': r"입주자모집공고일\s*현재\s*입주자저축\s*순위요건을\s*만족하였으나.{0,150}?청약이\s*불가합니다",
        'overseas': r"출입국사실증명서\s*(?:상\s*)?해외체류기간.{0,1300}?국내에\s*거주하고\s*있는\s*것으로\s*봅니다",
        'restriction': r"주택법.{0,180}?제64조\s*제?1항.{0,220}?\d+년간\s*입주자로\s*선정될\s*수\s*없습니다",
        'ineligible': r"부적격\s*당\s*첨자로\s*판명된\s*경우.{0,550}?입주자로\s*선정될\s*수\s*없습니다",
        'used': r"당첨\s*된\s*청약통장은\s*계약여부와\s*관계없이\s*재사용이\s*불가합니다",
        'bank': r"기관추천\(장애인.{0,2000}?\[\s*청약예금의\s*예치금액\s*\]",
        'once': r"특별공급은\s*무주택세대구성원에게\s*한\s*차례에.{0,320}?횟수\s*제한\s*예외\)",
        'foreign': r"외국인은.{0,250}?특별공급\s*청약이\s*불가합니다",
        'nomination': r"최초\s*입주자모집공고일\s*현재\s*무주택세대구성원으로서.{0,150}?추천\s*및\s*인정서류를\s*받으신\s*분",
        'general': r"2순위[^■]{0,350}?가입한\s*분",
        'summary': r"소득\s*또는\s*자산기준\s*-\s*-\s*적용\s*-\s*적용\s*적용\s*-\s*-",
        'domestic': r"국내에서\s*거주하는.{0,220}?외국인\s*포함",
    }
    evidence = {key: e(key, pattern) for key, pattern in common.items()}
    missing = {supply: [] for supply in offered}
    labels = {'active': '신청일의 청약통장 유지·해지 기준', 'overseas': '해외 연속체류·재입국·생업 예외',
              'restriction': '불법 전매·공급질서 위반의 신청 제한', 'ineligible': '부적격 당첨자 신청 제한',
              'used': '당첨 청약통장의 재사용 제한', 'bank': '공급유형별 통장 인정기간·예치금',
              'once': '특별공급 횟수 제한·면제', 'foreign': '특별공급 국적 범위', 'nomination': '기관추천 대상·추천 확인',
              'general': '일반공급 순위별 신청 통장', 'summary': '공급유형별 소득·자산 적용·면제표', 'domestic': '국내 거주 신청자 범위'}
    for key, anchor in evidence.items():
        if anchor:
            continue
        affected = [SPECIALS[0]] if key == 'nomination' else [s for s in offered if s != GENERAL] if key in {'once','foreign','bank'} else [GENERAL] if key == 'general' else offered
        for supply in affected:
            if supply in missing:
                missing[supply].append(labels[key])
    table, deposit_evidence = _deposit_values(pages)
    if table is None:
        for supply in offered:
            missing[supply].append('현재 공고의 지역·면적별 예치금 표 또는 서로 충돌하는 표')
    if any(missing.values()):
        return {'rules': rules, 'missing_topics': missing, 'conditional_topics': {}, 'exempt_topics': {},
                'review_version': REVIEW_VERSION, 'reviewed_pages': sorted(p['page'] for p in pages), 'completion_basis': 'document_structure_reviewed_standard_branch'}
    body = _normal(' '.join(p['text'] for p in pages))
    abroad = re.search(r"해외체류기간.{0,80}?계속하여\s*(\d+)일을\s*초과", evidence['overseas']['quote'])
    reentry = re.search(r"입국\s*후\s*(\d+)일\s*내\s*동일국가", evidence['overseas']['quote'])
    illegal = re.search(r"(\d+)년간\s*입주자로", evidence['restriction']['quote'])
    duration = re.search(r"수도권.{0,50}?(\d+)년", evidence['ineligible']['quote'])
    if not all((abroad, reentry, illegal, duration)):
        return {'rules': rules, 'missing_topics': {s: ['해외체류·청약제한의 숫자와 적용 범위'] for s in offered},
                'conditional_topics': {}, 'exempt_topics': {}, 'review_version': REVIEW_VERSION, 'reviewed_pages': sorted(p['page'] for p in pages)}
    months = {}
    for supply in offered:
        if supply == GENERAL:
            continue
        anchor = _find(scoped.get(supply, []), r"청약통장\s*가입기간\s*(\d+)개월\s*경과")
        if not anchor:
            return {'rules': rules, 'missing_topics': {s: ['유형별 청약통장 인정기간'] for s in offered}, 'conditional_topics': {}, 'exempt_topics': {}, 'review_version': REVIEW_VERSION, 'reviewed_pages': sorted(p['page'] for p in pages)}
        months[supply] = int(re.search(r"(\d+)개월", anchor['quote'])[1])
    nomination_body = _normal(' '.join(p['text'] for p in scoped.get(SPECIALS[0], [])))
    reasons = [label for label, pattern in [('장애인', '장애인'), ('국가유공자·보훈', '국가유공자|보훈'), ('중소기업 장기근속', '중소기업'), ('장기복무 군인', r'10년\s*이상\s*장기복무\s*군인'), ('북한이탈주민', '북한이탈주민')] if re.search(pattern, nomination_body)]
    layout = {'title': payload.get('title', ''), 'reasons': reasons, 'unsupported_reasons': ['기타'], 'finder': e,
              'unsupported_evidence': _find(scoped.get(SPECIALS[0], []), r'장기복무\s*제대군인[^■]{0,120}') or evidence['nomination']}
    if re.search(r'장기복무\s*제대군인', nomination_body) and '장기복무 군인' not in reasons:
        layout['unsupported_reasons'].insert(0, '장기복무 군인')
    if '국민기초생활' in body:
        layout['benefits'] = True
    first_body = _normal(' '.join(p['text'] for p in scoped.get(SPECIALS[4], [])))
    tax_years = _unique_int(r'(\d+)년\s*이상\s*소득세', first_body)
    recent_tax = _unique_int(r'과거\s*(\d+)년\s*내에\s*소득세', first_body)
    solo_area = _unique_int(r'단독세대\s*신청자는\s*전용면적\s*(\d+)㎡\s*이하', first_body)
    income_scope_body = _normal(' '.join(p['text'] for supply in (SPECIALS[2], SPECIALS[4], SPECIALS[5]) for p in scoped.get(supply, [])))
    ascendant = re.search(r'최근\s*(\d+)년\s*이상\s*계속하여\s*공급신청자', income_scope_body)
    income_age = re.search(r'가구원\s*중\s*만\s*(\d+)세\s*이상인\s*성년자', income_scope_body)
    general_accounts = _account_types(evidence['general']['quote'])
    special_accounts = _account_types(evidence['bank']['quote'])
    installment_limit = _unique_int(r'전용면적\s*(\d+)㎡\s*이하\s*주택형에\s*한함', evidence['bank']['quote'])
    if not general_accounts or not special_accounts or 'installment' in special_accounts and installment_limit is None:
        return {'rules': rules, 'missing_topics': {s: ['현재 공고의 통장 종류·청약부금 면적 범위'] for s in offered}, 'conditional_topics': {}, 'exempt_topics': {}, 'review_version': REVIEW_VERSION, 'reviewed_pages': sorted(p['page'] for p in pages)}
    account_fields = {'area_limit_for_installment': installment_limit} if installment_limit is not None else {}
    values = {'general_accounts': general_accounts, 'special_accounts': special_accounts, 'account_fields': account_fields,
              'general_account_fields': account_fields if 'installment' in general_accounts else {}, 'income_applies': income_applies, 'tax_years': tax_years, 'recent_tax_months': recent_tax*12 if recent_tax else None,
              'solo_max_area': solo_area, 'income_ascendant_months': int(ascendant[1])*12 if ascendant else None, 'income_member_age': int(income_age[1]) if income_age else None,
              'overseas_days': int(abroad[1]), 'reentry_days': int(reentry[1]), 'illegal_years': int(illegal[1]),
              'ineligible_months': int(duration[1]) * 12, 'deposit_table': table, 'deposit_evidence': deposit_evidence,
              'months': months, 'financial': {s: _financial_values(sections_by_supply.get(s), s) for s in (SPECIALS[2], SPECIALS[4], SPECIALS[5])}}
    review = _condition_model(pages, digest=digest, reviewed={'title': payload.get('title', ''), 'announcement_date': next(r['criterion_date'] for r in rules if r.get('criterion_date'))},
                              rules=rules, offered=offered, make=make, layout=layout, values=values)
    if review:
        head_applies, head_anchor = _summary_cells(pages, r"세대주\s*요건")
        for supply in offered:
            if head_applies.get(supply) is False:
                review["exempt_topics"].setdefault(supply, []).append({"topic": "세대주", "status": "not_applicable", "required": False, "waived_rule_kind": "household_head", "rule_ids": [], "evidence_page": head_anchor["page"], "evidence_text": head_anchor["quote"]})
            if income_applies.get(supply) is None:
                review["missing_topics"][supply].append("유형별 소득·자산 적용 또는 면제 범위")
            elif income_applies.get(supply) is True and supply not in {SPECIALS[2], SPECIALS[4], SPECIALS[5]}:
                review["missing_topics"][supply].append("이 유형에 추가된 소득·자산 기준")
        for supply, financial in values['financial'].items():
            extensions = list(financial.get('extensions', {}).values()) if financial.get('extensions') else [financial.get('extension', {})]
            issues = {extension.get('extra_person_formula_issue') for extension in extensions if extension.get('extra_person_formula_verified') is False}
            for issue in sorted(issues - {None}):
                review['conditional_topics'].setdefault(supply, []).append({'topic': issue, 'status': 'partial', 'required': False,
                    'phase': 'conditional_admission', 'rule_ids': [], 'reason': '공식 소득표의 마지막 가구원 수를 초과하는 경우에만 추가 산식 검토가 필요합니다.'})
        _validate_scoped_requirements(review, scoped)
        _review_general_baseline(review, pages, general_section=sections_by_supply.get(GENERAL), make=make)
        instruction = _application_guidance(pages, make=make)
        if instruction:
            review['rules'].append(instruction)
    return review


def _review_general_baseline(review, pages, *, general_section, make):
    rules = review['rules']
    adult = _find(_section_pages(general_section), r"만\s*(\d+)세\s*이상인\s*분\s*또는\s*(?:세대주인\s*미성년자\s*\([^)]*\)|다음\s*각\s*목에\s*해당하는\s*미성년자인\s*세대주)")
    ownership = _find(pages, r"\d+주택\s*이상\s*소유(?:하신\s*분|한\s*세대에\s*속한\s*분)도\s*(?:청약\s*)?1순위\s*자격이\s*부여됩니다")
    rewinning = _find(pages, r"재당첨\s*제한을\s*적용\s*받지\s*않으며.{0,160}?본\s*아파트\s*청약이\s*가능합니다")
    # In a closed ordinary applicant section, model the printed conditions;
    # no ownership condition is synthesized from a separate scoring table.
    qualification = re.split(r'당첨자\s*선정방법|■\s*당첨자\s*선정', _normal(' '.join(p['text'] for p in _section_pages(general_section))))[0]
    if not ownership and qualification and '무주택' not in qualification and '주택소유' not in qualification:
        ownership = {'page': general_section['page'], 'quote': qualification[:900]}
    for anchor, topic in ((adult, '성년·미성년 세대주 신청 범위'), (ownership, '일반공급의 주택 소유 허용 범위'), (rewinning, '현재 공고의 재당첨 제한·면제')):
        if not anchor:
            review['missing_topics'].setdefault(GENERAL, []).append(topic)
    if adult:
        value = int(re.search(r"만\s*(\d+)세", adult['quote'])[1])
        standard = make('age_min', value, operator='>=', unit='years', **adult)
        alternative = make('all', conditions=[make('household_head', True, **adult), make('unparsed', label='공고의 미성년 세대주 사유', text='미성년자는 자녀양육·형제자매 부양 등 공식 세대주 사유를 충족해야 합니다.', **adult)], **adult)
        rules.append(make('any', label='성년 또는 공고의 미성년 세대주', conditions=[standard, alternative], **adult))
    once = _find(pages, r'특별공급은\s*무주택세대구성원에게\s*한\s*차례에.{0,320}?횟수\s*제한\s*예외\)')
    for anchor, topic in ((ownership, '무주택 세대구성원'), (rewinning, '재당첨 제한'), (once, '특별공급 횟수 제한')):
        if anchor:
            review['exempt_topics'].setdefault(GENERAL, []).append({'topic': topic, 'status': 'not_applicable', 'required': False, 'rule_ids': [], 'evidence_page': anchor['page'], 'evidence_text': anchor['quote']})
    # Stock uncertainty belongs to every actual offered route; a collection of
    # matching applicant words cannot certify an inconsistent supply table.
    if any(r.get('inventory_status') in {'conflict','partial'} for r in rules if r['kind'] == 'offered_supplies'):
        for supply in review['missing_topics']:
            review['missing_topics'][supply].append('모집표의 공급유형·주택형별 물량 대조')


def _application_guidance(pages, *, make):
    """Keep application/paperwork procedures outside eligibility gaps."""
    items = []
    candidates = (
        ('같은 주택의 중복 신청', 'application', r'동일\s*주택에\s*대하여\s*특별공급과\s*일반공급.{0,350}?(?:모두\s*무효처리|모두\s*무효)'),
        ('부부 중복 당첨 처리', 'application', r'부부가\s*특별공급에\s*중복\s*당첨된\s*경우.{0,650}?(?:연장자|연령).{0,70}?(?:유효|당첨)'),
        ('당첨 후 자격 증빙·서류 제출', 'post_selection', r'서류\s*제출\s*기간\s*내에.{0,900}?계약(?:진행|\s*체결|을\s*체결)'),
    )
    proof = None
    for label, phase, pattern in candidates:
        anchor = _find(pages, pattern)
        if not anchor:
            continue
        evidence = make('application_instructions', effect='metadata', **anchor)
        proof = proof or evidence
        items.append({'label': label, 'phase': phase, 'detail': anchor['quote'], 'evidence_page': anchor['page'],
                      'evidence_text': anchor['quote'], 'evidence_url': evidence['evidence_url'], 'document_hash': evidence['document_hash']})
    if proof:
        proof['instructions'] = items
    return proof


def office_qualification(pages):
    """Discover the actual office applicant block, including reordered PDF dates."""
    candidates = []
    for page in pages:
        body = _normal(page['text'])
        heading = re.search(r'(?:청약|신청)\s*자격\s*및\s*유의사항|청약\s*신청\s*자격\s*및\s*공급일정', body)
        if not heading:
            continue
        start = heading.end()
        end_match = re.search(r'청약\s*일정\s*및\s*장소|청약신청\s*안내', body[start:])
        section = body[start:start + end_match.start()] if end_match else body[start:start + 2200]
        match = re.search(r'(?:분양|모집)광고일.{0,100}?대한민국에\s*거주하는.{0,450}?신청\s*가능(?:합니다|함)', section)
        if not match:
            continue
        # A PDF may place the age/date after the sentence and the next
        # bullet's duplicate-application counts before its glyph. Read only
        # this applicant bullet; numbers from the next procedure are not
        # alternative age values.
        tail = section[match.start():]
        stop = re.search(r'[•⦁■▣Ÿ]|청약\s*신청(?:은|이)', tail)
        quote = tail[:stop.start()] if stop else tail
        if stop and re.match(r'[•⦁■▣Ÿ]\s*청약\s*신청은\s*인당\s*개실', tail[stop.start():]):
            quote = re.sub(r'\s+(?:\d+\s*[,.;]*\s*){3}$', '', quote)
        dates = set()
        from datetime import date
        for y, m, d in re.findall(r'(20\d{2})[.년\-/]\s*(\d{1,2})[.월\-/]\s*(\d{1,2})', quote):
            try:
                dates.add(date(int(y), int(m), int(d)).isoformat())
            except ValueError:
                pass
        adult = re.search(r'(?:만\s*)?(\d+)세\s*이상인\s*자', quote)
        if adult:
            age = int(adult[1])
        elif re.search(r'만\s*세\s*이상인\s*자', quote):
            # The displaced date, age and opening inclusion bracket retain
            # their own token order. A new financial amount elsewhere in
            # this bullet must remain an auditable condition, not erase age.
            integers = re.findall(r'\(20\d{2}\.\d{1,2}\.\d{1,2}\.?\)\s*(\d{1,2})(?!\d)\s*\[', quote)
            if not integers:
                without_dates = re.sub(r'20\d{2}\.\d{1,2}\.\d{1,2}\.?', '', quote)
                integers = re.findall(r'(?<!\d)(\d{1,2})(?!\d)', without_dates)
            age = int(integers[0]) if len(integers) == 1 else None
        else:
            age = None
        if len(dates) == 1 and age is not None:
            candidates.append({'page': page['page'], 'quote': quote, 'age': age, 'date': next(iter(dates)), 'section': section})
    if len(candidates) != 1:
        return None
    return candidates[0]


def generic_office_admission(pages, *, make, cutoff):
    anchor = office_qualification(pages)
    if not anchor or anchor['date'] != cutoff:
        return {'rules': [], 'complete': False, 'missing_topics': ['현재 공고의 청약자격 문단·분양광고 기준일·성년 기준']}
    evidence = {'page': anchor['page'], 'quote': anchor['quote']}
    rules = [make('age_min', anchor['age'], supply=GENERAL, operator='>=', unit='years', **evidence),
             make('domestic_residence', True, supply=GENERAL, **evidence),
             make('applicant_regions', effect='metadata', scope_complete=True, unrestricted=True, domestic_only=True,
                  priority_applicable=False, **evidence)]
    # A corporate path is an optional alternative to this natural-person
    # standard branch, not an unanswered personal fact.
    missing = []
    for bullet in re.split(r'[•⦁■▣Ÿ]', anchor['section']):
        bullet = bullet.strip()
        if not bullet:
            continue
        remainder = _office_procedure_residual(bullet)
        if _office_mandatory_predicate(remainder):
            missing.append('오피스텔 추가 신청 조건: ' + remainder.strip()[:160])
    missing.extend(_office_document_admission_gaps(pages, anchor))
    instructions = _find(pages, r'(?:(?:\d+\s*[,.;]*\s*){3}[•⦁]\s*청약\s*신청은\s*인당|\d+인당|청약\s*신청은\s*(?:\d+)?인당).{0,180}?중복\s*신청.{0,100}?무효\s*처리\s*(?:합니다|되므로\s*유의하시기\s*바랍니다|됩니다)(?:\s*(?:\d+\s*[,.;]*\s*){3})?')
    if instructions:
        proof = make('application_instructions', effect='metadata', **instructions)
        proof['instructions'] = [{'label': '군별 신청 수·중복 신청 제한', 'phase': 'application', 'detail': instructions['quote'],
                                  'evidence_page': instructions['page'], 'evidence_text': instructions['quote'], 'evidence_url': proof['evidence_url'], 'document_hash': proof['document_hash']}]
        rules.append(proof)
    return {'rules': rules, 'complete': not missing, 'missing_topics': missing, 'review_version': REVIEW_VERSION,
            'reviewed_pages': sorted(p['page'] for p in pages)}


def _office_procedure_residual(text):
    """Remove closed application procedures, leaving new applicant predicates.

    A familiar applicant noun is not required: a new vehicle/financial/other
    limit is still an unreviewed eligibility fact. These patterns describe
    procedure outcomes, never an entire keyword-bearing bullet.
    """
    patterns = (
        r'(?:본\s*오피스텔(?:의)?\s*)?(?:최초\s*|금회\s*)?(?:분양|모집)광고일\s*(?:\(20\d{2}\.\d{1,2}\.\d{1,2}\.?\))?\s*현재\s*대한민국에\s*거주하는\s*(?:만\s*)?\d+세\s*이상인\s*자는\s*(?:청약\s*)?신청\s*가능(?:합니다|함)',
        r'(?:최초\s*|금회\s*)?(?:분양|모집)광고일\s*(?:\(20\d{2}\.\d{1,2}\.\d{1,2}\.?\))?\s*현재\s*대한민국에\s*거주하는\s*(?:만\s*)?(?:\d+)?세\s*이상인\s*자',
        r'또는\s*법인의\s*경우\s*신청\s*가능(?:합니다|함)',
        r'신청자의\s*착오로\s*인해\s*부적격자로\s*판명되는\s*경우[,\s]*계약체결이\s*불가하고\s*계약체결\s*이후에는\s*계약이\s*취소될\s*수\s*있으며\s*이에\s*대한\s*책임은\s*청약\s*신청자\s*본인에게\s*있습니다',
        r'청약신청은\s*청약Home을\s*통한\s*인터넷\s*청약접수를\s*원칙으로\s*하며\s*해당\s*신청일에\s*신청하지\s*않을\s*경우\s*청약이\s*불가합니다',
        r'거주\s*지역\s*및\s*청약\s*통장\s*가입\s*여부와\s*무관하게\s*청약\s*신청(?:이)?\s*가능합니다',
        r'청약\s*신청은\s*\d+인\s*\d+실\s*\(건\)만\s*(?:청약이\s*)?가능합니다',
        r'\d+인당\s*군별\s*\d+실\s*\(건\)\s*청약이\s*가능하며\s*\(각\s*군별\s*\d+건씩\s*[‘\']최대\s*\d+건[’\']\)',
        r'동일인이\s*(?:동일한\s*군에\s*)?\d+실\s*\(건\)\s*이상\s*중복\s*신청하는\s*경우\s*청약\s*신청\s*(?:모두|전부)(?:를|가)?\s*무효\s*처리\s*(?:되므로\s*유의하시기\s*바랍니다|됩니다|합니다)',
        r'청약\s*신청은\s*(?:\d+)?인당\s*(?:\d+)?개?실\s*청약\s*가능하며[,\s]*동일인이\s*(?:\d+)?개?실\s*이상\s*중복\s*신청하는\s*경우\s*청약\s*신청\s*(?:모두|전부)(?:를|가)?\s*무효\s*처리\s*(?:합니다|되므로\s*유의하시기\s*바랍니다|됩니다)',
        r'본\s*오피스텔은\s*아파트\s*청약통장\s*순위와\s*무관하므로,?\s*청약통장이\s*필요하지\s*않으며,?\s*청약홈에서\s*인터넷\s*청약을\s*신청하여\s*당첨되더라도\s*당첨자\s*관리\s*및\s*재당첨\s*제한\s*등은\s*적용되지\s*않습니다',
        r'청약자는\s*필히\s*본\s*공고\s*내용을\s*숙지하여\s*분양계약을\s*체결하여야\s*합니다',
        r'청약자\s*본인의\s*주민등록증\s*제출\s*생략\s*가능',
    )
    for pattern in patterns:
        text = re.sub(pattern, ' ', text)
    return text


def _office_mandatory_predicate(text):
    return re.search(r'이상|이하|초과|미만|필수|필요|해야|하여야|어야|여야|아야|(?:인|하는|받으신|받은|한|있는|없는)\s*(?:자|분)(?:만)?|(?:자|분)만|(?:청약|신청).{0,20}(?:불가|가능|할\s*수\s*없|제한)|자격.{0,20}(?:충족|만족)', text)


def _office_document_admission_gaps(pages, anchor):
    """Audit applicant clauses outside the primary qualification section.

    A document-wide review includes separately headed restrictions and direct
    applicant predicates wherever they occur. Application, refund, paperwork
    and contract blocks do not become applicant sections merely because they
    mention an applicant or a condition-checking procedure.
    """
    missing = []
    seen = set()
    reviewed = _normal(anchor['section'])
    applicant_section = False
    for page in pages:
        for block in re.split(r'(?=[■▣])', page['text']):
            block = block.strip()
            if not block:
                continue
            if block[0] in '■▣':
                heading_lines = block[1:].strip().splitlines()
                if not heading_lines:
                    continue
                heading = heading_lines[0]
                applicant_section = bool(re.search(r'^(?:(?:\d+|[ⅠⅡⅢⅣIVX]+)\s*)?(?:(?:별도|추가|기타|공통|필수|일반|특별)\s*)*(?:(?:청약\s*신청|청약|신청)\s*(?:자격|조건|제한|대상)|자격\s*(?:요건|조건))', heading))
            for clause in re.split(r'[•⦁Ÿ。;]|(?<!\d)\.(?!\d)', _normal(block)):
                clause = clause.strip()
                if not clause or (page['page'] == anchor['page'] and clause in reviewed):
                    continue
                remainder = _office_procedure_residual(clause).strip()
                direct_applicants = list(re.finditer(r'(?:청약|신청)\s*자(?:는|가|에게는|에게)\s*|^(?:청약|신청)\s*자\s+|(?:자|분|사람)(?:만|에\s*한하여)\s*(?:청약|신청)', remainder))
                direct_applicant = next((match for match in direct_applicants if _office_mandatory_predicate(remainder[match.start():])), None)
                if not (applicant_section or direct_applicant) or not _office_mandatory_predicate(remainder):
                    continue
                if not applicant_section and direct_applicant:
                    remainder = remainder[max(0, direct_applicant.start()-120):]
                key = (page['page'], remainder)
                if key not in seen:
                    seen.add(key)
                    missing.append(f"오피스텔 추가 신청 조건 ({page['page']}쪽): " + remainder[:180])
    return missing


def _summary_cells(pages, label):
    candidates = []
    for page in pages:
        lines = page['text'].splitlines()
        for index, line in enumerate(lines):
            if not re.search(label, line):
                continue
            preceding = ' '.join(lines[max(0, index-6):index])
            names = [(match.start(), name+' 특별공급') for name in ('기관추천','다자녀가구','신혼부부','노부모부양','생애최초','신생아') for match in re.finditer(name, preceding)]
            order = [name for _, name in sorted(names)]
            if len(order) != len(set(order)) or not order:
                continue
            # The closed summary header explicitly distinguishes general 1st
            # and 2nd rank. Their exemptions may not silently be merged.
            if not re.search(r'1순위\s*2순위', preceding):
                continue
            cells = re.findall(r'적용|필요|-', re.split(label, line)[-1])
            if len(cells) != len(order)+2 or cells[-1] != cells[-2]:
                continue
            mapping = {supply: cell != '-' for supply, cell in zip(order, cells)}
            mapping[GENERAL] = cells[-1] != '-'
            candidates.append((mapping, {'page': page['page'], 'quote': _normal(line)}))
    if not candidates or any(mapping != candidates[0][0] for mapping,_ in candidates):
        return {}, None
    return candidates[0]


def _summary_applies(pages):
    return _summary_cells(pages, r'소득\s*또는\s*자산기준')


def _validate_scoped_requirements(review, scoped):
    mandatory = {
        SPECIALS[0]: {'homeless','recommendation'}, SPECIALS[1]: {'homeless','children_min'},
        SPECIALS[2]: {'homeless','marital_status','marriage_months_max'},
        SPECIALS[3]: {'homeless','parent_age_min','parent_support_months_min','parent_same_register','household_head','parent_owns_home','parent_spouse_owns_home'},
        SPECIALS[4]: {'homeless','never_owned_home','first_home_family','first_home_tax_activity'},
        SPECIALS[5]: {'homeless','newborn_children_min'},
    }
    for supply, required in mandatory.items():
        if supply not in review['missing_topics']:
            continue
        kinds = {r['kind'] for r in review['rules'] if r.get('supply_type') == supply}
        missing = required - kinds
        if missing:
            review['missing_topics'][supply].append('신청자격 문단의 필수 조건 미확보: ' + ' · '.join(sorted(missing)))
    for supply, pages in scoped.items():
        if supply not in review['missing_topics']:
            continue
        qualification = re.split(r'당첨자\s*선정방법|■\s*당첨자\s*선정|배점항목', _normal(' '.join(p['text'] for p in pages)))[0]
        # Nomination confirmation/attendance procedures follow the actual
        # target paragraph and are application steps, not extra eligibility.
        if supply == SPECIALS[0]:
            qualification = re.split(r'유의사항|추천방법|선정방법|추천기관|구\s*분\s*관련\s*법규|구\s*분\s*해당\s*기관|당첨자\s*선정|■\s*\d+년\s*이상\s*장기복무\s*군인\s*:', qualification)[0]
        # Review predicates, rather than accepting a paragraph because one
        # known noun occurs in it. These patterns cover modeled facts only;
        # new requirements in the same sentence retain their own predicate.
        # The audit also sees sentences without PDF bullet glyphs.
        target = qualification.split('■', 1)[-1] if '■' in qualification else qualification
        for clause in re.split(r'■|[。;]|(?<!\d)\.(?!\d)|\n', target):
            remainder = _modeled_applicant_residual(clause)
            if re.search(r'이상|이하|초과|미만|필수|필요|해야|하여야|있어야|없어야|(?:인|하는|받으신|받은|한|있는|없는)\s*분|신청.{0,20}(?:불가|가능)|자격.{0,20}(?:충족|만족)', remainder):
                # Topic labels, legal references and connectors alone do not
                # describe a second criterion. A remaining substantive term
                # with an operative predicate does.
                substantives = re.sub(r'「[^」]*」|[\d\W]|(?:대상자|구분|내용|한함|경우|분으로|으로서|또한|그리고|동시에|계속하여)', '', remainder)
                if len(substantives) > 3:
                    review['missing_topics'][supply].append('모델에 반영되지 않은 신청 조항: ' + remainder.strip()[:180])


def _modeled_applicant_residual(text):
    """Remove closed modeled clauses, never whole keyword-bearing bullets."""
    patterns = (
        r'(?:최초\s*)?입주자모집공고일\s*현재\s*(?:(?:[가-힣]+(?:특별자치시|광역시|특별시|특별자치도|특례시|도|시|군|구)\s*(?:에|에서)?\s*)+|수도권\s*\([^)]*\)\s*(?:에|에서)?\s*)(?:거주하는|거주하거나|거주자|거주하고)',
        r'(?:수도권\s*\([^)]*\)|[가-힣]+(?:특례시|광역시|특별시|특별자치도|특별자치시|도|시|군))\s*(?:에\s*)?거주하는',
        r'만\s*\d+세\s*이상인\s*분\s*또는\s*세대주인\s*미성년자\s*\([^)]*\)',
        r'(?:무주택세대구성원|무주택세대주|무주택자)(?:으로서|이어야\s*함|이면\s*신청가능함)?',
        r'아래\s*해당\s*기관의\s*추천\s*및\s*인정서류를\s*받으신\s*분',
        r'청약통장\s*가입기간\s*\d+개월\s*경과\s*\([^)]*예치금액\s*이상\)\s*(?:한\s*분)?',
        r'입주자모집공고일\s*현재\s*혼인기간\([^)]*\)이\s*\d+년\s*이내인\s*분',
        r'만\s*\d+세\s*이상인\s*분\s*또는\s*다음\s*각\s*목에\s*해당하는\s*미성년자인\s*세대주',
        r'본\s*아파트는\s*(?:전\s*세대\s*전용면적\s*\d+㎡\s*초과|\d+㎡\s*이하\s*주택형이\s*없으므로)[^)]*?단독세대[^)]*?청약이\s*불가함',
        r'본\s*아파트는\s*전\s*세대\s*전용면적\s*\d+㎡\s*초과\s*주택형으로\s*공급하여\s*1인\s*가구\s*중\s*단독세대의\s*생애최초\s*특별공급\s*청약\s*신청\s*불가',
        r'혼인기간이\s*\d+년\s*이내\s*\([^)]*\)\s*인\s*분',
        r'만\s*\d+세\s*미만의\s*자녀\s*\d+명\s*이상\s*\((?:(?:태아|입양자녀|전혼자녀)\s*(?:[,·ㆍ]|및|또는)\s*)*(?:태아|입양자녀|전혼자녀)\s*포함\)\s*이\s*있는\s*분',
        r'만\s*\d+세\s*이상의\s*직계존속\s*\([^)]*\)을\s*\d+년\s*이상\s*계속하여\s*부양\s*\([^)]*\)\s*한\s*분',
        r'입주자모집공고일\s*현재\s*\d+세\s*미만\s*\([^)]*\)의\s*자녀\s*\([^)]*\)가\s*있는\s*분',
        r'「[^」]*」(?:에서\s*정하는|\s*제\d+조(?:제\d+항)?의)\s*(?:소득기준\s*또는\s*자산기준을\s*충족하는|1순위에\s*해당하는)\s*분',
        r'순위별\s*청약통장\s*자격요건을\s*만족(?:하는\s*분|하고|하며)',
        r'(?:최초\s*)?입주자모집공고일\s*현재\s*신청자의\s*청약통장\s*자격요건을\s*갖추어야\s*합니다',
        r'생애최초로\s*주택을\s*구입하는\s*분',
        r'모든\s*세대구성원이\s*과거\s*주택을\s*소유한\s*사실이\s*없는\s*경우를\s*말함',
        r'혼인\s*중이거나\s*미혼인\s*자녀\s*\([^)]*\)가\s*있는\s*분',
        r'1인\s*가구\s*\([^)]*없는\s*분\)',
        r'단독세대\s*신청자는\s*전용면적\s*\d+㎡\s*이하\s*주택형\s*에\s*한하\s*여\s*신청\s*가능함',
        r'입주자모집공고일\s*현재\s*근로자\s*또는\s*자영업자\*?로서\s*\d+년\s*이상\s*소득세를\s*납부\*?\*?한\s*분',
        r'과거\s*\d+년\s*내에\s*소득세\s*\([^)]*\)를\s*납부한\s*분을\s*포함',
        r'\d+년\s*이상\s*소득세\s*납부실적은\s*청약자\s*본인이\s*납부한\s*경우만\s*인정하며[^■]*?합산\s*불가',
        r'해당\s*주택에\s*신청가능한\s*청약예금에\s*가입하여\s*\d+개월이\s*경과하고,?\s*지역별·면적별\s*예치금액\s*이상인\s*분',
        r'청약부금에\s*가입하여\s*\d+개월이\s*경과하고,?\s*매월\s*약정납입일에\s*납부한\s*월납입인정금액이\s*예치금액\s*이상인\s*분',
        r'주택청약종합저축에\s*가입하여\s*\d+개월이\s*경과하고,?\s*지역별·면적별\s*예치금액\s*이상인\s*분',
        r'2순위\s*:\s*예치금액과\s*관계없이\s*(?:(?:청약예금|청약부금|주택청약종합저축)[·ㆍ\s]*)+에\s*가입한\s*분',
        r'아래\s*[‘\']가[’\']\s*또는\s*[‘\']나[’\']에\s*해당하는\s*분',
        r'1인\s*가구는\s*추첨제로만\s*신청가능하며',
        r'전용면적\s*\d+㎡\s*이하\s*(?:[\d,]+만원\s*){3}',
        r'(?:단,\s*)?장애인,\s*국가유공자\s*및\s*철거주택\s*소유자\s*\(도시재생\s*부지제공자\)는\s*청약통장\s*불필요',
        r'각\s*청약통장으로\s*신청가능한\s*전용면적\s*이하에\s*해당되는\s*주택형에만\s*청약가능함',
        r'가족관계증명서를\s*제출하여\s*미성년자임을\s*입증해야\s*함',
    )
    for pattern in patterns:
        text = re.sub(pattern, ' ', text)
    # Only the known installment area annotation is an explanation. Other
    # parenthetical predicates, including ones inside a familiar fact, retain
    # their own compulsory criteria for review.
    text = re.sub(r'\(전용면적\s*\d+㎡\s*이하\s*주택형에\s*한함\)', ' ', text)
    return text


def _unique_int(pattern, text):
    values = {int(value) for value in re.findall(pattern, text)}
    return next(iter(values)) if len(values) == 1 else None


def _account_types(text):
    names = [('comprehensive', '주택청약종합저축'), ('deposit', '청약예금'), ('installment', '청약부금')]
    return [kind for kind, term in names if term in re.sub(r'\s+', '', text)]
