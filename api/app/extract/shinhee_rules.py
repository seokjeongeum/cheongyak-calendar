"""A17's actual family routes, account and reviewed income/asset branches."""
import re

A17_HASH = "f591455563e503427c61699da3823b2029aa8ba24e3d09d84478ce01686d10e0"


def a17_conditions(pages, *, digest, make):
    if digest != A17_HASH:
        return None
    source={p["page"]:re.sub(r"\s+"," ",p["text"]) for p in pages}
    if not {2,8,10,11,12,15} <= source.keys():
        return None
    def e(page, pattern=None):
        m=re.search(pattern,source[page]) if pattern else None
        return {"page":page,"quote":m.group(0) if m else source[page][:850]}
    offered=[s+"(신혼희망타운)" for s in ("신혼부부","예비신혼부부","한부모가족")]
    rules=[make("rank_applicability",effect="metadata",status="not_applicable",account_required=True,
                reason="신혼희망타운 · 아파트 일반공급 1·2순위 적용 없음 · 유형별 통장 6개월·6회 요건 비교",**e(15,r"입주자저축에\s*가입하여\s*6개월[^■]{0,160}?6회[^■]{0,160}")),
           make("applicant_regions",effect="metadata",scope_complete=True,regions=[{"region_code":c,"region_name":n} for c,n in [("11","서울특별시"),("41","경기도"),("28","인천광역시")]],
                local_priority={"region_code":"28","region_name":"인천광역시","min_months":0},priority_applicable=True,**e(15,r"입주자모집공고일\s*현재\s*수도권[^■]{0,140}"))]
    rules[1]["exceptions"]=[make("military_service_years",effect="metadata",min_years=10,currently_serving=True,require_as_of_date=True,**e(8,r"10년\s*이상[^■]{0,300}"))]
    rules.append(make("citizenship",allowed_values=["korean"],**e(2,r"외국인의\s*경우[^■]{0,60}")))
    rules.append(make("overseas_residence",max_continuous_days=90,value_basis="continuous_days_including_reentry_within_7_days",livelihood_exception=True,**e(8,r"해외에\s*있으며[^■]{0,500}")))
    for page,text in source.items():
        if page > 3:
            continue
        for restriction,pattern in [("rewinning_restriction_active",r"재당첨\s*제한[^■]{0,450}?(?:불가|없습니다)"),("ineligible_restriction_active",r"부적격[^■]{0,450}?제한[^■]{0,150}?(?:불가|없습니다)")]:
            if re.search(pattern,text):
                rules.append(make("application_restriction",False,scope="household",restriction=restriction,**e(page,pattern)))
    inventory=[]
    tables={130:[9793892,11442863,12125081,12878142,13631203,14384265],140:[10547268,12323083,13057779,13868768,14679757,15490747],150:[11300645,13203303,13990478,14859395,15728312,16597229],200:[15067526,17604404,18653970,19812526,20971082,22129638],210:[15820902,18484624,19586669,20803152,22019636,23236120],220:[16574279,19364844,20519367,21793779,23068190,24342602]}
    child=make("children_min",1,child_age_max=7,child_age_inclusive=False,include_pregnancy=True,include_adoption=True,operator=">=",**e(15,r"6세\s*이하[^■]{0,140}?자녀"))
    for supply in offered:
        inventory.append({"supply_type":supply,"unit_type":None,"supply_count":None,**{k:v for k,v in make("offered_supplies",**e(15)).items() if k in {"verification","document_hash","criterion_date","evidence_url","evidence_text","evidence_page"}}})
        if supply.startswith("예비"):
            rules.append(make("unparsed",supply=supply,label="혼인으로 구성할 세대의 주택 소유",text="현재 가족 목록과 혼인으로 구성할 세대가 다를 수 있어 예정 배우자·예정 세대의 소유를 추가 대조해야 합니다.",**e(15,r"혼인으로\s*구성할\s*세대원[^■]{0,80}")))
        else:
            rules.append(make("homeless",True,supply=supply,**e(15,r"무주택세대구성원")))
        rules.append(make("subscription_months",6,supply=supply,operator=">=",housing_kind="national",**e(15,r"입주자저축에\s*가입하여\s*6개월[^■]{0,160}?6회[^■]{0,160}")))
        rules.append(make("recognized_payments_min",6,supply=supply,operator=">=",require_as_of_date=True,value_basis="announcement_balance",**e(15,r"입주자저축에\s*가입하여\s*6개월[^■]{0,160}?6회[^■]{0,160}")))
        rules.append(make("account_type",supply=supply,allowed_values=["comprehensive","savings"],**e(15,r"입주자저축에\s*가입하여[^■]{0,170}")))
        if supply.startswith("신혼부부"):
            rules.append(make("all",supply=supply,label="혼인·자녀 요건",conditions=[make("marital_status",allowed_values=["married"],**e(15)),make("any",conditions=[make("marriage_months_max",84,operator="<=",anniversary_limit=True,**e(15)),child],**e(15))],**e(15,r"혼인\s*중인[^■]{0,350}")))
        elif supply.startswith("예비"):
            rules.append(make("planned_marriage",True,supply=supply,must_prove_before="occupancy",**e(15,r"혼인을\s*준비\s*중인[^■]{0,500}")))
        else:
            rules.append(make("all",supply=supply,label="한부모가족·자녀 요건",conditions=[make("single_parent_family",True,**e(15)),child],**e(15,r"6세\s*이하[^■]{0,350}?한부모가족[^■]{0,180}")))
        rules.append(make("shinhee_income",supply=supply,value_basis="household_monthly_income",household_size_basis="official_income_household",min_household_size=3,
                    percentage_tables={str(percent):[{"household_size":i,"max_krw":amount} for i,amount in zip(range(3,9),amounts)] for percent,amounts in tables.items()},
                    normal_percent=130,dual_income_percent=200 if not supply.startswith("한부모") else None,child_relaxation_since="2023-03-28",**e(15,r"월평균소득[^■]{0,240}"),table_evidence_page=12,table_evidence_text=source[12][:2900]))
        rules.append(make("shinhee_assets",supply=supply,asset_basis="official_net_household",base_max_krw=362000000,one_child_max_krw=397000000,two_children_max_krw=431000000,child_relaxation_since="2023-03-28",**e(11)))
    rules.append(make("offered_supplies",effect="metadata",supplies=inventory,inventory_status="verified",**e(15)))
    return {"rules":rules,"offered":offered}
