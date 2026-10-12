"""Local interpretation of public residual-sale qualification clauses.

Admission facts come from the current document, never the provider's name or
the feed's public-sale category. Each source's clauses are interpreted again
and the resulting facts and unresolved clauses are bound to that source hash.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from urllib.parse import parse_qs, urlparse

from .application_regions import explicit_applicant_regions, region_catalog
from .residual_inventory import residual_document_inventory

TOPIC_LABELS = {
    "age": "성년·미성년 세대주 신청 조건", "domestic_residence": "신청 기준일의 국내 거주 조건",
    "citizenship": "외국인 신청 제한", "home_ownership": "세대의 주택·분양권 소유 및 예외",
    "family": "가족 유형별 신청 조건", "provider_employee": "공급기관 임직원 매입 제한 및 예외",
    "overseas_residence": "해외 연속 체류 90일 초과 제한·생업 예외",
    "original_contract_ownership": "최초 공고 당첨 후 계약에 따른 주택 소유 판정",
    "application_restrictions": "전매 위반 등 현재 신청 제한",
}
REVIEW_VERSION = "generic-admission-2026-10-12-public-v1"


def _normal(text):
    return re.sub(r"\s+", " ", text).strip()


def _flat(text):
    return re.sub(r"\s+", "", text)


def _heading(text):
    # Outlined PDF headings draw each word repeatedly. Collapse adjacent
    # identical words only in title discovery, preserving operative clauses.
    return _flat(re.sub(r"(\S+)(?:\s+\1(?=\s|$))+", r"\1", text))


def _match(pages, pattern, *, limit=None):
    for page in pages[:limit] if limit else pages:
        text = _normal(page["text"])
        found = re.search(pattern, text)
        if found:
            return {"page": page["page"], "text": found.group(0)}
    return None


def _employee_clause(pages):
    return _match(pages, r"(?:공사|LH공사|한국토지주택공사)\s*(?:全\s*)?임직원[^■•]{0,650}?"
                  r"(?:계약을\s*체결할\s*수\s*없습니다|취득이\s*원칙적으로\s*제한(?:되오니|됩니다|된다)?|"
                  r"취득(?:이|은)\s*제한\s*될\s*수[^■•]{0,100}?바랍니다|취득(?:이|은)\s*제한(?:됩니다|된다|되는|되어)|"
                  r"(?:신청|계약|매각)[^■•]{0,40}?제외(?:합니다|됩니다|되므로)?|이해관계자\s*제외|관련\s*규정을\s*반드시\s*확인하여\s*주시기\s*바랍니다)")


def _exemption_clause(pages, fallback):
    candidates = []
    pattern = (r"(?:주택\s*소유\s*여부|거주지역|입주자저축\s*가입\s*여부|청약저축(?:통장)?\s*가입여부)"
               r"[^■•※]{0,420}?(?:불문|관계없이|무관|불요)(?:[^■•※]{0,100}?소득\s*및\s*자산기준을\s*적용하지\s*않으며)?")
    for page in pages:
        for match in re.finditer(pattern, _normal(page["text"])):
            candidates.append({"page": page["page"], "text": match[0]})
    return max(candidates, key=lambda item: sum(term in _flat(item["text"]) for term in ("주택소유", "청약", "과거당첨", "소득", "자산")), default=fallback)


def parse_public_sale_rules(pages, *, url, digest, payload, parser_version):
    body = "\n".join(p["text"] for p in pages)
    flat = _flat(body)
    heading_parts = []
    for page in pages:
        # A standalone document heading can move with a cover sheet. Later
        # procedural paragraphs mentioning first-come contracts are excluded.
        lines = page["text"].splitlines()
        for index, line in enumerate(lines):
            joined = _heading(" ".join(lines[index:index + 2]))
            if re.match(r"[■•※▌]|(?:본|금회)(?:주택|공급)|당첨자|신청자", joined):
                continue
            if re.search(r"(?:잔여(?:세대|주택)|공가세대|자격완화|선착순)[^■]{0,140}(?:입주자모집\s*공고|일반매각\s*공고|모집\s*공고|일반매각[^■]{0,60}공고)|(?:입주자모집|일반매각)[^■]{0,50}공고[^■]{0,40}선착순", joined):
                heading_parts.append(joined)
    head = _flat(" ".join(heading_parts))
    # Ordinary initial shinhee applications (including A17) use the complete
    # numbered-section parser. Do not mistake later first-come instructions
    # within an ordinary announcement for the present application method.
    # Some PDFs draw a heading repeatedly to make outlined letters. The
    # resulting text can repeat '선착순' and the 동·호 tokens far apart. A
    # direct declaration about the present offering establishes the same
    # method without interpreting later leftover-contract instructions.
    firstcome_clause = _match(pages,
        r"(?:금회\s*공급(?:하는|되는)\s*주택(?:은|는)|본\s*공고(?:는|의\s*공급방식은))"
        r"[^■•。.]{0,150}?선착순\s*동[·ㆍ∙.]?\s*호(?:\s*지정)?"
        r"[^■•。.]{0,100}?(?:현장\s*계약|계약(?:체결)?)(?:만)?\s*(?:가능|진행|합니다|방식)") or _match(pages,
        r"본\s*공고는\s*선착순\s*상시계약\s*공고")
    firstcome = bool(firstcome_clause or re.search(r"선착순.{0,25}(?:동.?호|일반매각|계약)|일반매각.{0,15}선착순", head))
    residual = bool(re.search(r"잔여|공가세대", head)) and ("일반매각" in head or "입주자모집" in head)
    relaxed = "자격완화" in head
    if not (firstcome or residual or relaxed) or not re.search(r"금회공급|신청자격|자격요건", flat):
        return None
    # This route's supported public templates explicitly waive the savings
    # account. Without that clause, keep the ordinary detailed parser.
    exemption = _match(pages, r"(?:입주자\s*(?:저축|통장)|(?:주택)?(?:청약종합저축|종합청약저축)|청약저축(?:통장)?|청약통장)"
                       r"\s*(?:가입\s*여부[^■•]{0,420}?(?:불문|관계없이|무관)|(?:이|은|는)?\s*(?:불요|불필요|필요\s*없(?:음|습니다)))")
    if not exemption:
        return None
    shinhee = "신혼희망타운" in head
    office = "오피스텔" in head
    kind = "not_applicable" if office else "national" if re.search(r"(?:의한|해당하는|따른)\s*국민주택", body) else "unknown"
    method = "first_come" if firstcome else "unranked_after" if "무순위" in head else "optional_supply"
    criterion = _match(pages, r"(?:\(자격요건\)\s*)?(?:주택공급|분양)?계약\s*체결일\s*(?:기준|현재)[^■]{0,230}?(?:성년자|만\s*\d{1,2}\s*세)")
    basis = "contract_date" if criterion else "announcement"
    cutoff, cutoff_source = None, None
    if not criterion:
        cutoff_source = _match(pages, r"(?:이\s*주택의\s*|금회\s*공급하는\s*주택의\s*)?(?:입주자\s*모집공고일|매각공고일)(?:은|\s*[\[(])\s*(20\d{2})[.년\-/]\s*(\d{1,2})[.월\-/]\s*(\d{1,2})", limit=None)
        if cutoff_source:
            numbers = re.search(r"(20\d{2})[.년\-/]\s*(\d{1,2})[.월\-/]\s*(\d{1,2})", cutoff_source["text"])
            try:
                cutoff = date(*map(int, numbers.groups())).isoformat()
            except ValueError:
                pass
    expected_cutoff = str(payload.get("announcement_date") or "")[:10]
    if cutoff and expected_cutoff and cutoff != expected_cutoff:
        return {"rules": [], "offered_supply_types": [], "status": "unsupported", "identity_status": "mismatch",
                "reason": "현재 모집공고일과 원문의 신청 자격 기준일이 일치하지 않습니다."}
    criterion_conflicts = []
    for page in pages:
        normalized = _normal(page["text"])
        for anchor in re.finditer(r"(?:입주자\s*모집공고일|매각공고일|공고일)\s*\(\s*(20\d{2})[.년\-/]\s*(\d{1,2})[.월\-/]\s*(\d{1,2})[.일]?\s*\)\s*(?:기준|현재)", normalized):
            if _flat(normalized[max(0, anchor.start() - 10):anchor.start()]).endswith("최초"):
                continue
            try:
                operative_date = date(*map(int, anchor.groups())).isoformat()
            except ValueError:
                operative_date = None
            if basis == "announcement" and operative_date != (cutoff or expected_cutoff):
                criterion_conflicts.append({"item": "원문 신청자격 문단의 공고 기준일 불일치", "stage": "criterion_date",
                                           "evidence_page": page["page"], "evidence_text": anchor[0]})
    rules = []
    def make(name, value=None, *, supply=None, evidence=None, **fields):
        evidence = evidence or cutoff_source or criterion or {"page": 1, "text": _normal(pages[0]["text"])[:700]}
        identity = json.dumps([digest, name, supply, fields], ensure_ascii=False, sort_keys=True)
        result = {"id": "official-" + hashlib.sha256(identity.encode()).hexdigest()[:16], "kind": name,
            "verification": "official", "source": "official_document_parser", "parser_version": parser_version,
            "document_hash": digest, "evidence_url": url, "evidence_text": evidence["text"][:900], "evidence_page": evidence["page"],
            "criterion_date": cutoff, "criterion_basis": basis, **fields}
        if kind != "unknown":
            result["housing_kind"] = kind
        if value is not None:
            result["value"] = value
        if supply:
            result["supply_type"] = supply
        return result
    rules.append(make("application_method", method, effect="metadata", evidence=firstcome_clause or {"page": pages[0]["page"], "text": _normal(pages[0]["text"])[:800]},
                      offer_mode="relaxed_sale" if relaxed else "shinhee_residual" if shinhee else "residual_general_sale"))
    rules.append(make("rank_applicability", effect="metadata", status="not_applicable", account_required=False, evidence=exemption,
                      reason=("신혼희망타운 잔여주택" if shinhee else "선착순 계약" if firstcome else "잔여주택 자격완화·무순위 추첨") + " · 청약통장 불필요 · 아파트 1·2순위 적용 없음"))
    if kind != "unknown":
        rules.append(make("housing_classification", effect="metadata"))
    old_context = next((r.get("value", {}) for r in payload.get("rules", []) if r.get("kind") == "qualification_context"), {})
    context = {**old_context, "application_criterion_date": cutoff, "application_criterion_basis": basis}
    if cutoff:
        context["application_announcement_date"] = cutoff
    rules.append(make("qualification_context", context, effect="metadata"))
    supplies = [name + "(신혼희망타운)" for name in ("신혼부부", "예비신혼부부", "한부모가족")] if shinhee else ["일반공급"]
    inventory = [{"supply_type": supply, "unit_type": None, "supply_count": None,
                  **{k: v for k, v in make("offered_supplies", evidence=exemption).items() if k in {"verification", "evidence_url", "evidence_text", "evidence_page", "document_hash", "criterion_date"}}}
                 for supply in supplies]
    # A positive documented total may be published, but never copied to each
    # family route: shinhee routes compete for the same inventory.
    total = _match(pages, r"공급대상[^■❚]{0,160}?잔여(?:세대)?\s*([\d,]+)\s*세대")
    # The current residual count can follow the complex total; a bare '총' is
    # never enough to identify this offer's inventory, especially group PDFs.
    compound_total = _match(pages, r"공급대상[^■]{0,100}?([\d,]+)\s*세대\s*중\s*잔여\s*([\d,]+)\s*세대")
    if compound_total:
        numbers = re.search(r"([\d,]+)\s*세대\s*중\s*잔여\s*([\d,]+)\s*세대", compound_total["text"])
        rules.append(make("supply_inventory_summary", effect="metadata", evidence=compound_total,
            total_households=int(numbers[1].replace(",", "")), current_supply_count=int(numbers[2].replace(",", "")),
            official_supply_url=payload.get("official_url")))
        if not shinhee:
            inventory[0]["supply_count"] = int(numbers[2].replace(",", ""))
    elif total and not shinhee:
        number = re.search(r"잔여(?:세대)?\s*([\d,]+)\s*세대", total["text"])
        if number:
            inventory[0]["supply_count"] = int(number[1].replace(",", ""))
    documented_inventory = residual_document_inventory(pages)
    inventory_status = "verified" if all(row["supply_count"] is not None for row in inventory) else "partial"
    summary = next((rule for rule in rules if rule["kind"] == "supply_inventory_summary"), None)
    if documented_inventory.status == "verified":
        differs = summary and any(summary.get(key) != getattr(documented_inventory, key)
            for key in ("total_households", "current_supply_count"))
        if differs:
            inventory_status = "conflict"
        else:
            if not summary:
                first_row = documented_inventory.rows[0]
                rules.append(make("supply_inventory_summary", effect="metadata",
                    evidence={"page": first_row["evidence_page"], "text": first_row["evidence_text"]},
                    total_households=documented_inventory.total_households,
                    current_supply_count=documented_inventory.current_supply_count,
                    official_supply_url=payload.get("official_url")))
            if not shinhee:
                inventory = [{**row, **{key: value for key, value in make("offered_supplies",
                    evidence={"page": row["evidence_page"], "text": row["evidence_text"]}).items()
                    if key in {"verification", "evidence_url", "evidence_text", "evidence_page", "document_hash", "criterion_date"}}}
                    for row in documented_inventory.rows]
                inventory_status = "verified"
    elif documented_inventory.status != "missing":
        inventory_status = documented_inventory.status
    rules.append(make("offered_supplies", effect="metadata", supplies=inventory, inventory_status=inventory_status))
    domestic = _match(pages, r"(?:국내|대한민국|전국)[^■]{0,180}?(?:만\s*)?\d{1,2}\s*세\s*이상[^■]{0,100}?(?:성년자|인\s*자|무주택세대)")
    age = _match(pages, r"(?:만\s*)?(\d{1,2})\s*세\s*이상(?:의)?\s*(?:성년자|인\s*자|이면|무주택세대구성원)")
    foreign_bar = _match(pages, r"(?:외국인(?:의\s*경우|은)?[^■]{0,40}?(?:불가|불가능)|법인\s*및\s*외국인\s*신청불가)")
    home = _match(pages, r"(?:금회\s*공급[^■]{0,300}|기본\s*신청자격[^■]{0,180})무주택세대구성원")
    if not home and "무주택세대구성원" in flat and not re.search(r"주택소유여부.{0,180}(?:불문|관계없이)", flat[:18000]):
        home = _match(pages, r"(?:입주자모집공고일|매각공고일)[^■]{0,250}무주택세대구성원")
    unrestricted = _match(pages, r"(?:거주지역|거주지)[^■]{0,240}(?:불문|무관|관계없이)")
    if not unrestricted and domestic and ("전국" in domestic["text"] or re.search(r"국내(?:에|에서)?\s*거주(?:하는|\s*\([^)]*\)하는)", domestic["text"])) and not any(p["name"] in domestic["text"] for p in region_catalog()["provinces"]):
        unrestricted = domestic
    if unrestricted:
        rules.append(make("applicant_regions", effect="metadata", evidence=unrestricted, unrestricted=True, domestic_only=bool(domestic), priority_applicable=False, priority_division="none", scope_complete=True))
    # A section title such as '임직원 등 부동산 신규취득 제한 관련'
    # is not an exclusion. Read the operative clause through its outcome.
    provinces = {r["name"]: r["code"] for r in region_catalog()["provinces"]}
    if not unrestricted:
        def region_make(name, *, quote, page, **fields):
            return make(name, evidence={"text": quote, "page": page}, **fields)
        rules.extend(explicit_applicant_regions(pages, cutoff=cutoff or expected_cutoff, make=region_make, provinces=provinces))
    employee = _employee_clause(pages)
    topic_rules = {}
    for supply in supplies:
        facts = []
        if age:
            r = make("age_min", int(re.search(r"(\d{1,2})\s*세", age["text"])[1]), supply=supply, operator=">=", unit="years", evidence=age)
            minor = _match(pages, r"미성년자는[^■]{0,450}?같은\s*세대별\s*주민등록표에\s*등재되어\s*있어야\s*(?:합니다|함)")
            if minor:
                minor_flat = _flat(minor["text"].split("이 경우")[0].split("(이 경우")[0])
                reasons = []
                if re.search(r"자녀(?:를)?부양|형제자매또는자녀를부양", minor_flat):
                    reasons.append("support_children")
                if "형제자매" in minor_flat and re.search(r"직계존속의(?:사망|실종)[^■]{0,100}부양", minor_flat):
                    reasons.append("support_siblings_parents_dead_or_missing")
                minor_rule = make("minor_household_head", True, evidence=minor, reasons=reasons, required_same_register=True)
                if not reasons or ("형제자매" in minor_flat and "support_siblings_parents_dead_or_missing" not in reasons):
                    minor_rule = make("unparsed", evidence=minor, label="미성년 세대주의 공고상 부양 사유",
                                      text="현재 원문에 명시된 미성년 세대주의 부양 사유를 비교 모델에 반영하지 못했습니다.")
                r = make("any", supply=supply, label="성년 또는 공고의 미성년 세대주", evidence=minor,
                         conditions=[r, minor_rule])
            else:
                incomplete_minor = _match(pages, r"미성년자는[^■]{0,280}?세대주만\s*신청\s*가능(?:합니다|함)")
                if incomplete_minor:
                    r = make("any", supply=supply, label="성년 또는 공고의 미성년 세대주", evidence=incomplete_minor,
                             conditions=[r, make("unparsed", evidence=incomplete_minor, label="미성년 세대주의 부양 사유 및 같은 주민등록표 등재 조건",
                                                 text="미성년 세대주의 부양 사유와 같은 세대별 주민등록표 등재 조건의 완전한 문장을 확보하지 못했습니다.")])
            facts.append(("age", r))
        if domestic:
            facts.append(("domestic_residence", make("domestic_residence", True, supply=supply, evidence=domestic)))
        if foreign_bar:
            facts.append(("citizenship", make("citizenship", supply=supply, allowed_values=["korean"], evidence=foreign_bar)))
        if home:
            facts.append(("home_ownership", make("homeless", True, supply=supply, evidence=home)))
        if employee:
            # Clauses that say "may be restricted" require a documented review
            # if the applicant is an employee, rather than an invented approval.
            legal_family = bool(re.search(r"제\s*4\s*조\s*제?\s*1\s*항\s*제?\s*2\s*호\s*또는\s*제?\s*3\s*호", employee["text"]))
            explicit_family = bool(re.search(r"배우자\s*및\s*임직원\s*본인의\s*직계존[·ㆍ]?\s*비속", employee["text"]))
            fields = {"provider": "LH", "restriction_uncertain": bool(re.search(r"제한\s*될\s*수|원칙적으로\s*제한", employee["text"])),
                      "related_family_scope": "공직자윤리법 제4조제1항제2호 또는 제3호의 이해관계자" if legal_family else
                      "배우자 및 임직원 본인의 직계존·비속" if explicit_family else "공고가 정한 이해관계자"}
            if legal_family:
                fields.update(related_family_legal_basis="공직자윤리법 제4조제1항제2호·제3호",
                              restricted_person_basis="employee_or_legal_related_family_after_statutory_exclusions")
                if re.search(r"제\s*12\s*조\s*제?\s*4\s*항[^)]{0,100}?고지\s*거부\s*허가를\s*받은\s*사람은\s*제외", employee["text"]):
                    fields["related_family_exclusions"] = [{"legal_basis": "공직자윤리법 제12조제4항", "reason": "재산등록사항 고지 거부 허가"}]
            elif explicit_family:
                fields["restricted_person_basis"] = "employee_or_spouse_or_employee_lineal_family"
            else:
                fields["restricted_person_basis"] = "employee_or_source_defined_related_person"
            if re.search(r"계약을\s*체결할\s*수\s*없습니다|취득이\s*(?:원칙적으로\s*)?제한", employee["text"]):
                fields.update(criterion_basis="contract_date", criterion_date=None)
            facts.append(("provider_employee", make("provider_employee_restriction", False, supply=supply, evidence=employee, **fields)))
        if shinhee:
            child_evidence = _match(pages, r"(\d+)세\s*이하[^■]{0,90}?(?:자녀|태아)")
            child_limit = int(re.search(r"(\d+)세", child_evidence["text"])[1]) if child_evidence else None
            child = make("children_min", 1, child_age_max=child_limit + 1 if child_limit is not None else None,
                child_age_inclusive=False, include_pregnancy="태아" in flat, include_adoption="입양" in flat, operator=">=", evidence=child_evidence or home)
            if child_evidence is None:
                child = make("unparsed", label="자녀·태아 인정 연령과 범위", evidence=home,
                    text="해당 가족 분기의 자녀 연령 및 태아·입양 인정 범위를 원문에서 확보하지 못했습니다.")
            if supply.startswith("신혼부부"):
                marriage = _match(pages, r"혼인기간(?:이)?\s*(\d+)년\s*이내[^■]{0,140}?자녀")
                if marriage:
                    family = make("all", supply=supply, evidence=marriage, label="혼인·자녀 요건", conditions=[
                        make("marital_status", allowed_values=["married"], evidence=marriage),
                        make("any", evidence=marriage, conditions=[make("marriage_months_max",int(re.search(r"(\d+)년", marriage["text"])[1])*12,operator="<=",anniversary_limit=True,evidence=marriage),child])])
                    facts.append(("family", family))
            elif supply.startswith("예비"):
                family = _match(pages, r"예비신혼부부\s*:[^■]{0,270}?혼인사실[^■]{0,100}")
                if family:
                    facts.append(("family", make("planned_marriage", True, supply=supply, evidence=family, must_prove_before="occupancy")))
            else:
                family = _match(pages, r"한부모가족\s*:[^■]{0,300}?(?:부\s*또는\s*모|한부모가족)")
                if family:
                    facts.append(("family", make("all", supply=supply, label="한부모가족·자녀 요건", evidence=family,
                        conditions=[make("single_parent_family", True, evidence=family), child])))
        # Existing project winners/contracts are an explicit present restriction
        # only where the qualification clause prohibits them (e.g. Suwon A3).
        barred = _match(pages, r"기당첨자\s*및\s*계약자\s*\(본인\s*및\s*세대원\)[^■]{0,100}?청약불가")
        if barred:
            for restriction in ("prior_project_winner", "prior_project_contract"):
                project = _project_id(payload, context)
                facts.append(("application_restrictions", make("application_restriction", False, supply=supply, evidence=barred, scope="household", restriction=restriction, project_id=project)))
        for restriction, scope, pattern in (
            ("rewinning_restriction_active", "household", r"재당첨\s*제한\s*대상\s*주택에\s*당첨된\s*자의\s*세대에\s*속하여\s*재당첨\s*제한\s*기간\s*중에\s*있는\s*분은\s*청약할\s*수\s*없습니다"),
            ("ineligible_restriction_active", "applicant", r"부적격\s*당첨자로\s*처리되어\s*당첨이\s*취소된\s*자는[^■]{0,220}?입주자로\s*선정될\s*수\s*없는"),
            ("resale_restriction_active", "applicant", r"주택의\s*전매행위\s*제한을\s*위반한\s*경우[^■]{0,160}?입주자격을\s*제한합니다"),
        ):
            evidence = _match(pages, pattern)
            if evidence:
                facts.append(("application_restrictions", make("application_restriction", False, supply=supply, evidence=evidence,
                    scope=scope, restriction=restriction)))
        extended = _residual_ownership_and_stay(pages, make=make, payload=payload, context=context, supply=supply)
        facts.extend(extended)
        if any(topic == "overseas_residence" for topic, _ in extended):
            for topic, rule in facts:
                if topic == "domestic_residence":
                    rule["overseas_residence_equivalence"] = True
        rules.extend(r for _,r in facts)
        topic_rules[supply] = facts
    exempt_topics = []
    # Some templates place home ownership and income before the account name.
    # Keep the complete explicit waiver clause, rather than its trailing half.
    whole_exemption = _exemption_clause(pages, exemption)
    exemption_flat = _flat(whole_exemption["text"])
    for topic, pattern in [("account", r"(?:입주자(?:저축|통장)|(?:주택)?(?:청약종합저축|종합청약저축)|청약저축(?:통장)?|청약통장)(?:가입여부|(?:이|은|는)?(?:불요|불필요|필요없))"), ("income",r"소득"), ("assets",r"자산"), ("home_ownership",r"주택소유여부"), ("prior_win",r"과거당첨")]:
        if re.search(pattern, exemption_flat) and (topic != "home_ownership" or not home):
            exempt_topics.append(topic)
    waiver = _match(pages, r"계약\s*체결\s*시에도[^■•]{0,100}?재당첨\s*제한[^■•]{0,100}?적용되지[^■•]{0,50}")
    existing_contractors = _match(pages, r"기계약자\s*및\s*그\s*세대원도\s*신청이\s*가능")
    if waiver:
        exempt_topics.extend(t for t in ("rewinning_restriction", "prior_win") if t not in exempt_topics)
    if existing_contractors:
        exempt_topics.extend(t for t in ("prior_project_contract", "prior_project_winner") if t not in exempt_topics)
    if exempt_topics:
        rules.append(make("condition_exemptions", effect="metadata", topics=exempt_topics, evidence=whole_exemption,
            descriptions={"account":"청약통장 가입 여부 무관", "income":"소득 기준 적용 없음", "assets":"자산 기준 적용 없음", "home_ownership":"유주택자 신청 가능", "prior_win":"과거 당첨 사실 무관", "rewinning_restriction":"재당첨 제한 적용 없음", "prior_project_contract":"이 사업 기존 계약자와 세대원도 신청 가능", "prior_project_winner":"과거 당첨 사실 무관"}))
    cap = _match(pages, r"분양가\s*상한제(?:가)?\s*(?:적용(?:되는|주택)|미적용|비적용|적용되지)")
    if cap:
        cap_value = "no" if re.search(r"미적용|비적용|적용되지", cap["text"]) else "yes"
        rules.append(make("price_cap", cap_value, effect="metadata", evidence=cap))
    instructions = []
    duplicate = _match(pages, r"동일블록\s*내\s*중복신청이[^■]{0,1000}?후\s*접수분은\s*무효처리\s*합니다") or _match(pages, r"(?:동일블록\s*내\s*중복신청|1세대\s*2인\s*이상)[^■]{0,1000}")
    if duplicate:
        instructions.append({"label": "동일 세대·블록 중복 신청과 공고의 부부 예외", "detail": duplicate["text"],
            "phase": "application", "evidence_page": duplicate["page"], "evidence_text": duplicate["text"], "evidence_url": url, "document_hash": digest})
    one_home = _match(pages, r"1인\s*1주택\s*기준으로\s*공급(?:합니다|하며)")
    if one_home:
        instructions.append({"label": "1인 1주택 신청·계약", "detail": one_home["text"],
            "phase": "application", "evidence_page": one_home["page"], "evidence_text": one_home["text"], "evidence_url": url, "document_hash": digest})
    post = _match(pages, r"당첨자\(?예비입주자\)?[^■]{0,100}(?:제출서류|서류제출)[^■]{0,200}")
    if post:
        instructions.append({"label": "당첨 후 서류 제출·계약 절차", "detail": post["text"], "phase": "post_selection",
            "evidence_page": post["page"], "evidence_text": post["text"], "evidence_url": url, "document_hash": digest})
    for label, phase, pattern in (
        ("토지거래허가 사전협의·서류 제출", "contract", r"(?:금회\s*공급되는\s*주택은)[^■•]{0,700}?협의\s*결과에\s*따라\s*계약이\s*가능합니다\.?\s*\([^)]*허가대상\)"),
        ("토지거래허가 후 이용 의무", "post_contract", r"토지거래허가\s*협의가\s*성립되면[^■•]{0,650}?불이익\s*조치가\s*있을\s*수\s*있습니다"),
        ("기존 공사 임대주택의 반환", "occupancy", r"(?:우리\s*공사|우리공사)\s*임대주택에\s*거주[^■•]{0,300}?명도\s*\(반환\)\s*하여야\s*합니다"),
    ):
        evidence = _match(pages, pattern)
        if evidence:
            instructions.append({"label": label, "phase": phase, "detail": evidence["text"],
                "evidence_page": evidence["page"], "evidence_text": evidence["text"], "evidence_url": url, "document_hash": digest})
    if instructions:
        rules.append(make("application_instructions", effect="metadata", evidence=duplicate or one_home or post or
                          {"page": instructions[0]["evidence_page"], "text": instructions[0]["evidence_text"]}, instructions=instructions))
    # Coverage is built from the current operative clauses, not a remembered
    # hash or project. Unknown eligibility terms remain concrete source gaps.
    scopes = []
    page_numbers = sorted({p["page"] for p in pages})
    contiguous = bool(page_numbers and page_numbers == list(range(page_numbers[0], page_numbers[-1] + 1)))
    expected_pages = payload.get("document_page_count")
    if type(expected_pages) is int and expected_pages > 0 and len(page_numbers) != expected_pages:
        contiguous = False
    applicant_section = _match(pages, r"(?:\d+\.\s*)?신청\s*자격[^■]{0,350}|기본\s*신청자격[^■]{0,350}|자격요건[^■]{0,350}")
    for supply, facts in topic_rules.items():
        kinds = {topic for topic, _ in facts}
        required = ["age", "domestic_residence"] + (["home_ownership", "family"] if shinhee else [])
        for topic, phrase in (("overseas_residence", "국외에계속하여"), ("original_contract_ownership", "당첨이후계약")):
            if phrase in flat and topic not in required:
                required.append(topic)
        if "무주택세대구성원" in flat and "home_ownership" not in exempt_topics and "home_ownership" not in required:
            required.append("home_ownership")
        if foreign_bar:
            required.append("citizenship")
        if re.search(r"임직원[^■•]{0,450}(?:취득|계약)", body) and "provider_employee" not in required:
            required.append("provider_employee")
        missing = [topic for topic in required if topic not in kinds]
        source_gaps = [{"item": TOPIC_LABELS.get(topic, topic), "topic": topic, "stage": "clause_extraction"} for topic in missing]
        source_gaps.extend(criterion_conflicts)
        if not applicant_section:
            source_gaps.append({"item": "현재 신청자격 문단의 시작과 범위", "stage": "section_discovery"})
        if not contiguous:
            source_gaps.append({"item": "신청 자격 검토 중 누락된 원문 페이지", "stage": "document_text"})
        source_gaps.extend(_unmodeled_admission(pages, facts, exempt_topics))
        def unread_clauses(rule):
            if rule.get("kind") == "unparsed":
                yield rule
            for field in ("conditions", "exceptions"):
                for child in rule.get(field) or []:
                    yield from unread_clauses(child)
        source_gaps.extend({"item": unread.get("label") or "신청 조건의 미확보 예외", "stage": "clause_extraction",
            "evidence_page": unread.get("evidence_page"), "evidence_text": unread.get("evidence_text")}
            for _, rule in facts for unread in unread_clauses(rule))
        if basis != "contract_date" and not cutoff:
            source_gaps.append({"item": "공식 신청 자격 기준일", "stage": "criterion_date"})
        complete = bool(facts and applicant_section and not source_gaps)
        branches = [{"branch_id": "adult", "label": "성년 개인 신청자", "status": "verified", "required": True,
                     "rule_ids": [r["id"] for _, r in facts], "requirements": sorted(kinds)}]
        if any(rule["kind"] == "any" and any(child["kind"] == "minor_household_head" for child in rule.get("conditions", [])) for _, rule in facts):
            branches.append({"branch_id": "minor_household_head", "label": "공고의 미성년 세대주", "status": "verified", "required": True,
                             "rule_ids": [rule["id"] for topic, rule in facts if topic == "age"],
                             "requirements": ["공고에 명시된 자녀 또는 형제자매 부양 사유", "부양 자녀·형제자매의 같은 세대별 주민등록표 등재"]})
        if employee:
            branches.append({"branch_id": "provider_employee", "label": "공급기관 임직원·공고가 정한 이해관계자", "status": "verified", "required": True,
                             "rule_ids": [r["id"] for topic, r in facts if topic == "provider_employee"], "evidence_page": employee["page"], "evidence_text": employee["text"]})
        if re.search(r"법인(?:에게|\s*(?:계약\s*)?가능)", flat):
            branches.append({"branch_id": "corporate", "label": "법인 계약의 대표·위임 서류", "status": "not_applicable", "required": False,
                             "phase": "application", "reason": "개인 프로필 신청자격 비교 범위 밖의 법인 계약 절차"})
        scopes.append({"supply_type": supply, "complete": complete, "verified_rule_count": len(facts),
            "missing_topics": list(dict.fromkeys(gap["item"] for gap in source_gaps)),
            "topics": [{"topic": topic, "status": "verified", "required": True,
                        "rule_ids": [r["id"] for t, r in facts if t == topic]} for topic in sorted(kinds)]
                + [{"topic": t, "status": "not_applicable", "required": False, "rule_ids": [],
                    "evidence_page": (waiver if t == "rewinning_restriction" and waiver else whole_exemption)["page"],
                    "evidence_text": (waiver if t == "rewinning_restriction" and waiver else whole_exemption)["text"],
                    "evidence_url": url, "document_hash": digest} for t in exempt_topics],
            "source_gaps": source_gaps, "reviewed_document_hash": digest,
            "review_version": REVIEW_VERSION, "reviewed_pages": page_numbers,
            "reviewed_section_pages": sorted({r["evidence_page"] for _, r in facts}),
            "branches": branches, "completion_basis": "current_document_clause_coverage" if complete else None})
    complete = bool(scopes and all(s["complete"] for s in scopes))
    rules.append(make("condition_coverage", effect="metadata", status="complete" if complete else "partial", scopes=scopes,
        offered_supply_types=supplies, covered_supply_types=[s for s,f in topic_rules.items() if f],
        completion_basis="current_document_clause_coverage" if complete else "validated_residual_qualification_clauses"))
    return {"rules":rules,"offered_supply_types":supplies,"offered_supplies":inventory,"status":"complete" if complete else "partial","parser_version":parser_version}


def _project_id(payload, context):
    # Reuse a supplied verified stable identity, or retain the current source's
    # exact identity. A project title never creates a fictitious project ID.
    if context.get("project_id"):
        return context["project_id"]
    query = parse_qs(urlparse(payload.get("official_url") or "").query)
    return payload.get("external_id") or (query.get("panId") or query.get("houseManageNo") or [None])[0]


def _residual_ownership_and_stay(pages, *, make, payload, context, supply):
    facts = []
    overseas = _match(pages, r"입주자모집공고일을\s*기준으로\s*국외에\s*계속하여\s*(\d+)일을\s*초과하여[^■]{0,650}?청약\s*가능\)")
    exception = _match(pages, r"세대원\s*중\s*주택공급신청자만[^■]{0,280}?단독세대주\s*또는\s*동거인의\s*세대원[^■]{0,80}?해당없음\)")
    returned = _match(pages, r"입주자모집공고일\s*전일[^■]{0,230}?청약신청\s*가능[^■]{0,180}?계속\s*거주한\s*것으로\s*간주")
    if overseas:
        days = int(re.search(r"계속하여\s*(\d+)일", overseas["text"])[1])
        reentry = re.search(r"(?:입국일부터|입국일로부터)\s*(\d+)일\s*이내", overseas["text"])
        fields = {"max_continuous_days": days, "value_basis": "continuous_days_including_reentry_within_7_days" if reentry else "continuous_days",
            "currently_abroad_only": bool(returned), "reentry_same_country": bool(reentry),
            "reentry_within_days": int(reentry[1]) if reentry else None}
        if exception:
            fields.update(livelihood_exception=True, livelihood_exception_requires_family=True,
                livelihood_exception_excludes=["sole_household_head", "cohabitant_household_member"],
                exception_evidence_text=exception["text"], exception_evidence_page=exception["page"])
        elif "생업" in overseas["text"]:
            fields["exceptions"] = [make("unparsed", label="생업 목적 국외 체류의 세대 예외", evidence=overseas,
                text="원문의 생업 목적 국외 체류 예외 적용 범위를 확보하지 못했습니다.")]
        if returned:
            fields.update(return_evidence_text=returned["text"], return_evidence_page=returned["page"])
        facts.append(("overseas_residence", make("overseas_residence", supply=supply, evidence=overseas, **fields)))
    ownership = _match(pages, r"최초\s*입주자모집\s*\((20\d{2})[.년/-]\s*(\d{1,2})[.월/-]\s*(\d{1,2})\)[^■]{0,250}?당첨\s*이후\s*계약[^■]{0,250}?신청\s*불가능합니다")
    permission = _match(pages, r"공고일\([^)]*\)\s*기준\s*최초\s*입주자모집공고\([^)]*\)[^■]{0,260}?당첨[^■]{0,260}?신청\s*가능합니다")
    if ownership and permission:
        dt = re.search(r"최초\s*입주자모집\s*\((20\d{2})[.년/-]\s*(\d{1,2})[.월/-]\s*(\d{1,2})", ownership["text"])
        original = date(*map(int, dt.groups())).isoformat()
        context["original_announcement_date"] = original
        facts.append(("original_contract_ownership", make("original_project_contract_ownership", supply=supply, evidence=ownership,
            project_id=_project_id(payload, context), scope="applicant", original_announcement_date=original,
            requires_original_winning=True, ownership_effect="contract_date", first_winning_alone_allowed=True,
            ineligible_winning_alone_allowed="부적격" in permission["text"],
            permission_evidence_text=permission["text"], permission_evidence_page=permission["page"])))
    return facts


def _modeled_numeric_requirement(required, sentence, facts):
    """Match a threshold to its implemented predicate, not an evidence token.

    Domestic-residence and family evidence can quote multiple requirements.
    The presence of a number in that quotation does not model its subject.
    Only supported numeric rule fields and their closed source phrases can
    account for a threshold in the current applicant sentence.
    """
    def children(rule):
        yield rule
        for field in ("conditions", "exceptions"):
            for child in rule.get(field) or []:
                yield from children(child)

    for _, fact in facts:
        for rule in children(fact):
            kind = rule["kind"]
            specifications = []
            if kind == "age_min":
                specifications.append((r"(?:만\s*)?(\d+)\s*세\s*이상(?:의)?\s*(?:성년자|인\s*(?:분|자)|무주택세대구성원)", rule.get("value"), 1))
            elif kind == "marriage_months_max":
                specifications.append((r"혼인기간(?:이)?\s*(\d+)\s*년\s*이내", rule.get("value"), 12))
                specifications.append((r"혼인기간(?:이)?\s*(\d+)\s*개월\s*이내", rule.get("value"), 1))
            elif kind == "children_min":
                maximum = rule.get("child_age_max")
                if isinstance(maximum, int) and not isinstance(maximum, bool):
                    inclusive = maximum if rule.get("child_age_inclusive") else maximum - 1
                    specifications.append((r"(?:만\s*)?(\d+)\s*세\s*이하[^■]{0,100}?자녀", inclusive, 1))
                    exclusive = maximum + 1 if rule.get("child_age_inclusive") else maximum
                    specifications.append((r"만\s*(\d+)\s*세\s*미만[^■]{0,100}?자녀", exclusive, 1))
            elif kind == "overseas_residence":
                specifications.append((r"국외에\s*계속하여\s*(\d+)\s*일(?:을)?\s*초과", rule.get("max_continuous_days"), 1))
                specifications.append((r"국외에\s*체류중이나[^■]{0,70}?체류기간이\s*연속\s*(\d+)\s*일\s*이하", rule.get("max_continuous_days"), 1))
                specifications.append((r"(?:입국일부터|입국일로부터)\s*(\d+)\s*일\s*이내", rule.get("reentry_within_days"), 1))
            for pattern, value, multiplier in specifications:
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                for match in re.finditer(pattern, sentence):
                    # Closed subject phrases and the implemented numeric value
                    # establish the same predicate even when a later reminder
                    # omits "의" or uses a supported permission paraphrase.
                    # An unrelated subject sharing the number still cannot
                    # match one of these subject-specific patterns.
                    if (match.start() <= required.start() and required.end() <= match.end()
                            and int(match[1]) * multiplier == value):
                        return True
    return False


def _unmodeled_admission(pages, facts, exempt_topics):
    """Report recognized unmodeled gates with their current source text."""
    gaps = []
    modeled = {r["kind"] for _, r in facts}
    restrictions = {r.get("restriction") for _, r in facts if r["kind"] == "application_restriction"}
    numeric_requirement = re.compile(r"(?:\d[\d,.]*|[일이삼사오육칠팔구십백천만억]+)\s*(?:세|년|개월|일|명|가구|세대|점|천만원|만원|억원|원|%|㎡)\s*(?:이상|이하|초과|미만|이내)")
    for page in pages:
        normalized = _normal(page["text"])
        for clause in re.split(r"[■▌•]", normalized):
            flat = _flat(clause)
            applicant_residual = _applicant_procedure_residual(flat)
            mandatory_applicant = bool(re.search(r"(?:신청자|청약자)(?:는|가|만)[^■]{0,180}?"
                r"(?:해야|하여야|이어야|있어야|없어야|받아야|[가-힣]+(?:어야|여야|아야)|필수|불가)", applicant_residual))
            mandatory_account = bool(re.search(r"(?:입주자저축|청약저축|청약통장|청약종합저축|종합청약저축)[^■]{0,60}(?:가입하여야|가입해야|보유하여야|보유해야)", flat))
            if not mandatory_applicant and not mandatory_account and not re.search(r"신청(?:이)?(?:가능|불가|불가능)|청약(?:이|할수)?(?:가능|불가|없)|입주자격을제한|신청자격|자격요건|재당첨제한대상주택|국외에계속하여|최초입주자모집\(.{0,160}당첨", flat):
                continue
            topic = None
            if mandatory_account:
                topic = "청약통장 가입 필수 조건과 면제 조항의 적용 범위"
            elif re.search(r"소득.{0,120}(?:이하|초과|이상|충족)|자산.{0,120}(?:이하|초과|이상|충족)", flat) and not {"income", "assets"} <= set(exempt_topics):
                topic = "소득·자산 신청 한도와 예외"
            elif re.search(r"재당첨제한대상주택에당첨된자의세대에속하여재당첨제한기간중", flat) and "rewinning_restriction_active" not in restrictions and "rewinning_restriction" not in exempt_topics:
                topic = "현재 재당첨 제한의 신청 배제 범위"
            elif re.search(r"최초입주자모집\(.{0,160}당첨이후계약", flat) and "original_project_contract_ownership" not in modeled:
                topic = "최초 당첨·계약에 따른 주택 소유 판정과 신청 허용 예외"
            elif re.search(r"국외에계속하여\d+일", flat) and "overseas_residence" not in modeled:
                topic = "국외 연속 체류 제한과 국내 거주 인정 예외"
            elif re.search(r"(?:벌점|신용점수|체납|근무기간|특정직종|별도자격)[^■]{0,200}(?:신청|청약)|(?:다른|별도|추가)(?:필수)?(?:신청자격|자격요건)", flat):
                topic = "비정형 신청 제한·요건"
            elif re.search(r"(?:무주택세대주|무주택세대구성원|무주택자)[^■]{0,80}(?:만신청|이어야|여야)", flat) and "homeless" not in modeled:
                topic = "세대의 무주택·세대주 신청 조건"
            elif re.search(r"(?:등록자|보유자|가입자|근로자|자격증|등록장애인)[^■]{0,100}(?:만신청|이어야|여야)", flat):
                topic = "모델에 반영되지 않은 신청 조항: " + _normal(clause)[:150]
            elif mandatory_applicant:
                # New nonnumeric gates also remain visible; document-reading,
                # viewing and payment obligations belong to contract procedure.
                topic = "비정형 신청 제한·요건" if numeric_requirement.search(clause) else "모델에 반영되지 않은 신청 조항: " + _normal(clause)[:150]
            if not topic:
                # An unfamiliar subject can appear beside a supported age or
                # residence rule. Check every numeric application threshold,
                # rather than accepting a whole bullet because one term was
                # recognized. Procedural deadlines have no application gate.
                for sentence in re.split(r"(?<=[.!?])\s+", clause):
                    if not re.search(r"(?:신청|청약)(?:신청)?\s*(?:이|할\s*수)?\s*(?:가능|불가|불가능|없)|신청자격|자격요건", sentence):
                        continue
                    for required in numeric_requirement.finditer(sentence):
                        if _modeled_numeric_requirement(required, sentence, facts):
                            continue
                        topic = "비정형 신청 제한·요건"
                        clause = sentence
                        break
                    if topic:
                        break
            if topic:
                gap = {"item": topic, "stage": "clause_extraction", "evidence_page": page["page"], "evidence_text": clause[:900]}
                if not any(g["item"] == topic and g["evidence_text"] == gap["evidence_text"] for g in gaps):
                    gaps.append(gap)
    return gaps


def _applicant_procedure_residual(text):
    """Remove closed procedure predicates, preserving other gates beside them."""
    for pattern in (
        r"(?:공급)?신청자는공고일당시세대주및세대구성원의주민등록표등본제출",
        r"(?:해당순번의)?신청자는지체없이동[·ㆍ‧.]?호를지정(?:하여야|해야)(?:하며|합니다)",
        r"(?:청약자|신청자)는반드시(?:세대개방일|주택개방일)에주택을방문하여세대내부를확인하시기바라며",
        r"신청자는반드시본인이주택개방일에현장\(기타단지여건,세대내부상태,마감재등\)을확인후계약하여야하며",
        r"신청자는기타단지여건,세대내부상태,마감재등은반드시본인이사전주택개방일에현장을확인후계약하여야하며",
        r"서류를반드시사전에발급받아지참한신청자만계약체결이가능하며",
        r"주택공급신청자가주택공급신청시알아야할사항",
        r"청약자는청약시[‘'「]?개인정보제공및활용[’'」]?과[‘'「]?정보의제3자제공[’'」]?에동의해야합니다",
    ):
        text = re.sub(pattern, " ", text)
    return text
