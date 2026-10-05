"""Hash-reviewed regional boundaries and positive supply-table allocations."""
import re


def regional_supplement(pages, *, reviewed, cutoff, make):
    if not reviewed or not reviewed.get("regional_review"):
        return {"rules": [], "supplies": [], "offered": []}
    source = {p["page"]: p["text"] for p in pages}
    required = {reviewed["region_page"], reviewed["inventory_page"]}
    if not required <= source.keys():
        return {"rules": [], "supplies": [], "offered": []}
    def evidence(page, pattern=None):
        text = re.sub(r"\s+", " ", source[page])
        m = re.search(pattern, text) if pattern else None
        return {"page":page,"quote":m.group(0) if m else text[:900]}
    rules, supplies = [], []
    for unit, counts in reviewed["inventory_units"].items():
        if not re.search(re.escape(unit.lstrip("0")) + r"\b", source[reviewed["inventory_page"]]):
            continue
        for supply, count in zip(reviewed["inventory_columns"], counts):
            if count <= 0:
                continue
            anchor = evidence(reviewed["inventory_page"], re.escape(unit.lstrip("0")) + r"[^\n]{0,500}")
            item = make("offered_supplies", **anchor)
            supplies.append({"supply_type": supply,"unit_type":unit,"supply_count":count,
                **{k:item.get(k) for k in ("verification","evidence_url","evidence_text","evidence_page","document_hash","criterion_date")}})
    offered = list(dict.fromkeys(row["supply_type"] for row in supplies))
    # Do not publish a partial table as a complete inventory.
    expected = sum(c > 0 for counts in reviewed["inventory_units"].values() for c in counts)
    if len(supplies) != expected:
        return {"rules": [], "supplies": [], "offered": []}
    rules.append(make("offered_supplies", effect="metadata", supplies=supplies, inventory_status="verified", **evidence(reviewed["inventory_page"])))
    areas = reviewed.get("exclusive_areas", {})
    if areas:
        rules.append(make("unit_exclusive_areas", effect="metadata", units=[{"unit_type": unit, "exclusive_area_sqm": area} for unit, area in areas.items()], **evidence(reviewed["inventory_page"])))
    fields = {"regions":reviewed["regions"],"scope_complete":True,"priority_applicable":reviewed.get("priority_applicable",False)}
    if reviewed.get("local_priority"):
        fields["local_priority"] = {**reviewed["local_priority"],"criterion_date":cutoff}
    if reviewed.get("military_exception"):
        anchor = evidence(reviewed.get("military_page",reviewed["region_page"]),r"10년\s*이상[^■]{0,450}")
        fields["exceptions"] = [make("military_service_years", effect="metadata", require_as_of_date=True, **reviewed["military_exception"], **anchor)]
    region_anchor = evidence(reviewed["region_page"], r"입주자모집공고일\s*현재[^■]{0,750}")
    rules.append(make("applicant_regions",effect="metadata",**fields,**region_anchor))
    adult_page = reviewed.get("adult_or_minor_page")
    if adult_page and adult_page in source:
        age_anchor = evidence(adult_page,r"(?:대상자|입주자모집공고일)[^■]{0,600}?(?:미성년자|성년자)[^■]{0,150}")
        rules.append(make("any",label="성년 또는 공고의 미성년 세대주",conditions=[make("age_min",19,operator=">=",**age_anchor),make("all",label="미성년 세대주의 부양 예외",conditions=[make("household_head",True,**age_anchor),make("unparsed",label="미성년 세대주의 부양 요건",text="공고가 정한 자녀 양육 또는 형제자매 부양 사실과 증빙을 추가 대조해야 합니다.",**age_anchor)],**age_anchor)],**age_anchor))
    for supply in offered:
        alternatives = [make("residence_region",**region,**region_anchor) for region in reviewed["regions"]]
        if fields.get("exceptions"):
            military = fields["exceptions"][0]
            alternatives.append({**military,"effect":None,"value":military["min_years"],"currently_serving":True})
        rules.append(make("any",supply=supply,label="신청 가능한 지역",conditions=alternatives,**region_anchor))
    if reviewed.get("price_cap_status"):
        rules.append(make("price_cap",reviewed["price_cap_status"],effect="metadata",**evidence(reviewed["price_cap_page"],r"분양가상한제[^■]{0,220}")))
    return {"rules":rules,"supplies":supplies,"offered":offered}


def residual_special_conditions(pages, *, reviewed, offered, make):
    """The two reviewed cancellation documents have different actual subtypes."""
    if not reviewed or reviewed["title"] not in {"고양 장항 아테라", "탕정 푸르지오 리버파크"}:
        return []
    def anchor(pattern, limit=900):
        for page in pages:
            text=re.sub(r"\s+"," ",page["text"])
            found=re.search(pattern,text)
            if found:
                return {"page":page["page"],"quote":found.group(0)[:limit]}
        return None
    rules=[]
    for supply in offered:
        for name,pattern,value,fields in [
            ("homeless",r"입주자모집공고일\s*현재[^■]{0,260}?무주택세대(?:구성원|주)",True,{}),
            ("citizenship",r"외국인\s*제외",None,{"allowed_values":["korean"]}),
        ]:
            e=anchor(pattern)
            if e: rules.append(make(name,value,supply=supply,**fields,**e))
        e=anchor(r"만19세\s*이상인\s*분\s*또는\s*세대주인\s*미성년자[^■]{0,80}")
        if e:
            rules.append(make("any",supply=supply,label="성년 또는 공고의 미성년 세대주",conditions=[make("age_min",19,operator=">=",**e),make("minor_household_head",True,required_same_register=True,reasons=["support_children","support_siblings_parents_dead_or_missing"],**e)],**e))
        if supply in {"일반공급","노부모부양 특별공급"}:
            e=anchor(r"(?:무주택세대주|무주택세대의\s*세대주)")
            if e: rules.append(make("household_head",True,supply=supply,**e))
        if supply.startswith("노부모"):
            for kind,value,pattern in [("parent_age_min",65,r"만65세\s*이상[^■]{0,180}"),("parent_support_months_min",36,r"3년\s*이상\s*계속하여\s*부양[^■]{0,180}"),("parent_same_register",True,r"같은\s*세대별\s*주민등록표등본[^■]{0,130}")]:
                e=anchor(pattern)
                if e:rules.append(make(kind,value,supply=supply,**e))
            e=anchor(r"피부양[^■]{0,250}?(?:배우자|무주택)")
            if e:
                rules.append(make("parent_owns_home",False,supply=supply,**e))
                rules.append(make("parent_spouse_owns_home",False,supply=supply,**e))
            # The document allows childbirth exemption with disposal conditions.
            # Keep the branch unverified until the required consent/proof facts
            # are supported; a homeowner isn't rejected without considering it.
            birth=anchor(r"출산특례[^■]{0,600}?(?:기존주택|처분)")
            if birth:
                for r in rules:
                    if r.get("supply_type")==supply and r["kind"]=="homeless":
                        r["exceptions"]=[make("unparsed",label="출산특례의 기존주택 처분 요건",text="2024.6.19 이후 출생 자녀·기존 특별공급 당첨 및 처분 승낙·입주 전 처분 증빙을 대조해야 합니다.",**birth)]
        if supply.startswith("생애최초"):
            for kind,value,pattern,fields in [
                ("never_owned_home",True,r"생애최초[^■]{0,280}?소유[^■]{0,200}",{"scope":"household","exclude_spouse_pre_marriage_disposed":True}),
                ("tax_years_min",5,r"5년\s*이상\s*소득세를\s*납부[^■]{0,240}",{}),
                ("first_home_tax_activity",True,r"근로자\s*또는\s*자영업자[^■]{0,280}",{"tax_years_min":5,"includes_tax_exemption":True,"recent_tax_months":12}),
                ("first_home_family",True,r"1인\s*가구[^■]{0,500}",{"solo_max_area_sqm":60,"include_adoption":True,"include_pregnancy":False}),
            ]:
                e=anchor(pattern)
                if e: rules.append(make(kind,value,supply=supply,**fields,**e))
            e=anchor(r"160%이하[^■]{0,1200}?(?:331|3\.31)[^■]{0,200}")
            if e:
                table=make("monthly_income_max_krw",supply=supply,value_basis="household_monthly_income",household_size_basis="official_income_household",min_household_size=3,
                    income_table=[{"household_size":size,"max_krw":amount} for size,amount in zip(range(3,9),(12054021,14083523,14923176,15850021,16776866,17703710))],extra_person_krw=579278,**e)
                property=make("real_estate_max_krw",331000000,supply=supply,operator="<=",asset_basis="real_estate",**e)
                rules.append(make("any",supply=supply,label="월평균소득 또는 부동산 기준",conditions=[table,property],**e))
    return rules
