"""Local interpretation of public residual-sale qualification clauses.

Admission facts come from the current document, never the provider's name or
the feed's public-sale category. Reviewed hashes certify a bounded set of
mandatory topics; a corrected document must be reviewed again for completeness.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from .gajeong_admission import GAJEONG_HASH, GAJEONG_REVIEW, gajeong_admission

# Full applicant sections, exemptions and employee clauses compared with the
# source PDFs. These certify admission, not contract/payment obligations.
REVIEWED_ADMISSION = {
    GAJEONG_HASH: GAJEONG_REVIEW,
    "4be040db7f7562135ed57584edede4b9c497eee536fbd686ac20642c13301855": {"pages": [1, 2], "topics": ["age", "domestic_residence", "provider_employee"]},
    "d33f83bc20f2fd5caeea78007e948a9becd46e51426f27f82e5b984d4f531f00": {"pages": [1, 3], "topics": ["age", "domestic_residence"]},
    "91eb4846a866e763b87e0c00b640e9f13dfe78442cda5d69cdac45c8c5a01492": {"pages": [1, 2, 4], "topics": ["age", "domestic_residence", "citizenship", "provider_employee"]},
    # Cheongju Jibuk B1: complete current admission sections (1, 2, 8),
    # including explicit homeowner/prior-winner/current-contractor permission.
    # The minor exception remains a conditional branch in the browser; the
    # reviewed adult branch does not need the minor's unprovided facts.
    "b6102a6e202fecebed1256f0d18f5404c7e8d033f4920cc59487c31eeff6d770": {"pages": [1, 2, 8], "topics": ["age", "domestic_residence", "citizenship", "provider_employee"]},
}

TOPIC_LABELS = {
    "age": "성년·미성년 세대주 신청 조건", "domestic_residence": "신청 기준일의 국내 거주 조건",
    "citizenship": "외국인 신청 제한", "home_ownership": "세대의 주택·분양권 소유 및 예외",
    "family": "가족 유형별 신청 조건", "provider_employee": "공급기관 임직원 매입 제한 및 예외",
    "overseas_residence": "해외 연속 체류 90일 초과 제한·생업 예외",
    "original_contract_ownership": "최초 공고 당첨 후 계약에 따른 주택 소유 판정",
    "application_restrictions": "전매 위반 등 현재 신청 제한",
}


def _normal(text):
    return re.sub(r"\s+", " ", text).strip()


def _flat(text):
    return re.sub(r"\s+", "", text)


def _match(pages, pattern, *, limit=None):
    for page in pages[:limit] if limit else pages:
        text = _normal(page["text"])
        found = re.search(pattern, text)
        if found:
            return {"page": page["page"], "text": found.group(0)}
    return None


def parse_public_sale_rules(pages, *, url, digest, payload, parser_version):
    body = "\n".join(p["text"] for p in pages)
    flat = _flat(body)
    head = _flat(re.split(r"공급위치|공급대상|알\s*려\s*드\s*립", pages[0]["text"])[0])
    # Ordinary initial shinhee applications (including A17) use the complete
    # numbered-section parser. Do not mistake later first-come instructions
    # within an ordinary announcement for the present application method.
    firstcome = bool(re.search(r"선착순.{0,25}(?:동.?호|일반매각|계약)|일반매각.{0,15}선착순", head))
    residual = "잔여" in head and ("일반매각" in head or "입주자모집" in head)
    relaxed = "자격완화" in head
    if not (firstcome or residual or relaxed) or not re.search(r"금회공급|신청자격|자격요건", flat):
        return None
    # This route's supported public templates explicitly waive the savings
    # account. Without that clause, keep the ordinary detailed parser.
    exemption = _match(pages, r"(?:입주자\s*(?:저축|통장)|청약저축|청약통장)[^■•]{0,420}?(?:불문|관계없이|무관|불요)")
    if not exemption:
        return None
    shinhee = "신혼희망타운" in head
    office = "오피스텔" in head
    kind = "not_applicable" if office else "national" if re.search(r"(?:의한|해당하는|따른)\s*국민주택", body) else "unknown"
    method = "first_come" if firstcome else "optional_supply"
    criterion = _match(pages, r"(?:\(자격요건\)\s*)?(?:주택공급|분양)?계약\s*체결일\s*(?:기준|현재)[^■]{0,230}?(?:성년자|만\s*19세)")
    basis = "contract_date" if criterion else "announcement"
    cutoff, cutoff_source = None, None
    if not criterion:
        cutoff_source = _match(pages, r"(?:이\s*주택의\s*|금회\s*공급하는\s*주택의\s*)?(?:입주자\s*모집공고일|매각공고일)(?:은|\s*[\[(])\s*(20\d{2})[.년\-/]\s*(\d{1,2})[.월\-/]\s*(\d{1,2})", limit=10)
        if cutoff_source:
            numbers = re.search(r"(20\d{2})[.년\-/]\s*(\d{1,2})[.월\-/]\s*(\d{1,2})", cutoff_source["text"])
            try:
                cutoff = date(*map(int, numbers.groups())).isoformat()
            except ValueError:
                pass
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
    rules.append(make("application_method", method, effect="metadata", evidence={"page": 1, "text": _normal(pages[0]["text"])[:800]},
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
    total = _match(pages, r"공급대상[^■❚]{0,160}?잔여(?:세대)?\s*([\d,]+)\s*세대", limit=3) or _match(pages, r"총\s*([\d,]+)\s*세대", limit=3)
    if total and not shinhee:
        number = re.search(r"잔여(?:세대)?\s*([\d,]+)\s*세대", total["text"]) or re.search(r"([\d,]+)\s*세대", total["text"])
        inventory[0]["supply_count"] = int(number[1].replace(",", ""))
    rules.append(make("offered_supplies", effect="metadata", supplies=inventory, inventory_status="verified"))
    domestic = _match(pages, r"(?:국내|대한민국|전국)[^■]{0,180}?(?:만\s*)?19\s*세\s*이상[^■]{0,100}?(?:성년자|인\s*자|무주택세대)")
    age = _match(pages, r"(?:만\s*)?19\s*세\s*이상(?:의)?\s*(?:성년자|인\s*자|이면)")
    foreign_bar = _match(pages, r"(?:외국인(?:의\s*경우|은)?[^■]{0,40}?(?:불가|불가능)|법인\s*및\s*외국인\s*신청불가)")
    home = _match(pages, r"(?:금회\s*공급[^■]{0,300}|기본\s*신청자격[^■]{0,180})무주택세대구성원")
    if not home and "무주택세대구성원" in flat and not re.search(r"주택소유여부.{0,180}(?:불문|관계없이)", flat[:18000]):
        home = _match(pages, r"(?:입주자모집공고일|매각공고일)[^■]{0,250}무주택세대구성원")
    unrestricted = _match(pages, r"(?:거주지역|거주지)[^■]{0,240}(?:불문|무관|관계없이)") or domestic
    if unrestricted:
        rules.append(make("applicant_regions", effect="metadata", evidence=unrestricted, unrestricted=True, domestic_only=bool(domestic), priority_applicable=False, priority_division="none", scope_complete=True))
    # A section title such as '임직원 등 부동산 신규취득 제한 관련'
    # is not an exclusion. Read the operative clause through its outcome.
    employee = _match(pages, r"(?:공사|LH공사|한국토지주택공사)\s*(?:全)?임직원[^■]{0,360}?(?:제외|제한\s*될\s*수|취득(?:이|은)\s*제한(?:됩니다|된다|되는|되어)|확인하여)")
    topic_rules = {}
    for supply in supplies:
        facts = []
        if age:
            r = make("age_min", 19, supply=supply, operator=">=", unit="years", evidence=age)
            minor = _match(pages, r"미성년자는[^■]{0,450}?같은\s*세대별\s*주민등록표")
            if minor:
                r = make("any", supply=supply, label="성년 또는 공고의 미성년 세대주", evidence=minor,
                         conditions=[r, make("minor_household_head", True, evidence=minor, reasons=["support_children", "support_siblings_parents_dead_or_missing"], required_same_register=True)])
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
            facts.append(("provider_employee", make("provider_employee_restriction", False, supply=supply, evidence=employee,
                provider="LH", restriction_uncertain=bool(re.search(r"제한\s*될\s*수", employee["text"])), related_family_scope="배우자 및 임직원 본인의 직계존·비속")))
        if shinhee:
            child = make("children_min", 1, child_age_max=7, child_age_inclusive=False, include_pregnancy=True, include_adoption=True, operator=">=", evidence=_match(pages, r"6세\s*이하[^■]{0,90}?(?:자녀|태아)") or home)
            if supply.startswith("신혼부부"):
                marriage = _match(pages, r"혼인기간(?:이)?\s*7년\s*이내[^■]{0,140}?자녀")
                if marriage:
                    family = make("all", supply=supply, evidence=marriage, label="혼인·자녀 요건", conditions=[
                        make("marital_status", allowed_values=["married"], evidence=marriage),
                        make("any", evidence=marriage, conditions=[make("marriage_months_max",84,operator="<=",anniversary_limit=True,evidence=marriage),child])])
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
                project = "LH-SUWON-DANGSU-A3" if "수원당수" in head and "A-3" in head else None
                facts.append(("application_restrictions", make("application_restriction", False, supply=supply, evidence=barred, scope="household", restriction=restriction, project_id=project)))
        rules.extend(r for _,r in facts)
        topic_rules[supply] = facts
    exempt_topics = []
    # Some templates place home ownership and income before the account name.
    # Keep the complete explicit waiver clause, rather than its trailing half.
    whole_exemption = _match(pages, r"(?:금회\s*(?:공급하는|공급되는|공고)[^■•]{0,80})?(?:주택\s*소유\s*여부|거주지역|입주자저축\s*가입\s*여부|청약저축\s*가입여부)[^■•]{0,420}?(?:불문|관계없이|무관|불요)") or exemption
    exemption_flat = _flat(whole_exemption["text"])
    for topic, pattern in [("account", r"입주자(?:저축|통장)|청약저축|청약통장"), ("income",r"소득"), ("assets",r"자산"), ("home_ownership",r"주택소유여부"), ("prior_win",r"과거당첨")]:
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
    gajeong = gajeong_admission(pages, digest=digest, make=make)
    if gajeong:
        rules.extend(rule for _, rule in gajeong["facts"])
        rules.extend(gajeong["metadata"])
        topic_rules["일반공급"].extend(gajeong["facts"])
        context["original_announcement_date"] = gajeong["original_announcement_date"]
        for rule in rules:
            if rule["kind"] == "domestic_residence":
                rule["overseas_residence_equivalence"] = True
        if gajeong["inventory"]:
            inventory = gajeong["inventory"]
            rules = [r for r in rules if r["kind"] != "offered_supplies"]
            rules.append(make("offered_supplies", effect="metadata", supplies=inventory, inventory_status="verified", evidence={"page": 3, "text": " / ".join(s["evidence_text"] for s in inventory)}))
    review = REVIEWED_ADMISSION.get(digest)
    reviewed_pages = {p["page"] for p in pages}
    scopes = []
    for supply, facts in topic_rules.items():
        kinds = {topic for topic,_ in facts}
        required = review["topics"] if review else ["age", "domestic_residence"] + (["home_ownership", "family"] if shinhee else [])
        missing = [topic for topic in required if topic not in kinds]
        complete = bool(review and set(review["pages"]) <= reviewed_pages and not missing and (basis == "contract_date" or cutoff))
        source_gaps = []
        if review:
            absent_pages = sorted(set(review["pages"]) - reviewed_pages)
            if absent_pages:
                source_gaps.append({"item": "검토한 원문 페이지 미확보", "pages": absent_pages, "stage": "document_text"})
            source_gaps.extend({"item": TOPIC_LABELS.get(topic, topic), "topic": topic, "stage": "clause_extraction"} for topic in missing)
        else:
            # Concrete unreviewed admission areas, rather than treating
            # submission or payment procedures as unknown eligibility.
            source_gaps = [{"item": item, "stage": "admission_review"} for item in (
                "국내 거주·해외 연속 체류 제한 및 예외", "주택·분양권·기존 사업 계약의 신청 제한 및 예외",
                "청약 제한의 적용·면제", "공급기관 임직원 매입 제한의 적용·면제")]
        if basis != "contract_date" and not cutoff:
            source_gaps.append({"item": "공식 신청 자격 기준일", "stage": "criterion_date"})
        missing = list(dict.fromkeys([TOPIC_LABELS.get(topic, topic) for topic in missing] + [gap["item"] + (" (" + ", ".join(map(str, gap["pages"])) + "쪽)" if gap.get("pages") else "") for gap in source_gaps]))
        scopes.append({"supply_type":supply,"complete":complete,"verified_rule_count":len(facts),"missing_topics":missing,
            "topics":[{"topic":topic,"status":"verified","required":True,"rule_ids":[r["id"] for t,r in facts if t==topic]} for topic in sorted(kinds)]
               +[{"topic":t,"status":"not_applicable","required":False,"rule_ids":[]} for t in exempt_topics],
            "source_gaps": source_gaps, "reviewed_document_hash": digest if review else None,
            "reviewed_section_pages": review.get("reviewed_section_pages", review["pages"]) if review else [],
            "branches": review.get("branches", []) if review else [],
            "completion_basis":"document_hash_review" if complete else None})
    complete = bool(scopes and all(s["complete"] for s in scopes))
    rules.append(make("condition_coverage", effect="metadata", status="complete" if complete else "partial", scopes=scopes,
        offered_supply_types=supplies, covered_supply_types=[s for s,f in topic_rules.items() if f],
        completion_basis="document_hash_review" if complete else "validated_residual_qualification_clauses"))
    return {"rules":rules,"offered_supply_types":supplies,"offered_supplies":inventory,"status":"complete" if complete else "partial","parser_version":parser_version}
