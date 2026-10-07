"""Current official region boundaries, real inventories and public-sale modes."""
import json
from pathlib import Path
import pytest
from app.extract.official_rules import parse_official_rules, document_cutoff
from app.qualification import public_offered_supplies, requirements_complete
from app.extract.reprocess import _document_patch
from app.extract.pipeline import find_document_links

FIXTURES = Path(__file__).parent / 'fixtures'
REGIONAL = json.loads((FIXTURES / 'regional-v5.json').read_text())
PUBLIC = json.loads((FIXTURES / 'public-v5.json').read_text())
CURRENT_PRIVATE = json.loads((FIXTURES / 'current-private-v5.json').read_text())

def parse(row, changed=False):
    return parse_official_rules(row['pages'], url=row['document_url'], digest='changed-document' if changed else row['document_hash'], payload=row.get('payload'))

def by_number(number):
    return next(r for r in REGIONAL if r['house_manage_no'] == number)

def rules_of(parsed, kind):
    return [r for r in parsed['rules'] if r['kind'] == kind]

@pytest.mark.parametrize('number,scope,types,cap',[
    ('2026910251','서울특별시',{'일반공급'},'no'),
    ('2026930038','경기도 고양시',{'일반공급','노부모부양 특별공급'},'yes'),
    ('2026930039','충청남도 아산시',{'생애최초 특별공급'},'yes'),
    ('2026000444','제주특별자치도',{'일반공급'},None),
    ('2026000498','충청남도',{'일반공급','기관추천 특별공급','다자녀가구 특별공급','신혼부부 특별공급','노부모부양 특별공급','생애최초 특별공급','신생아 특별공급'},None),
])
def test_actual_region_inventory_and_caps(number,scope,types,cap):
    result=parse(by_number(number))
    assert set(result['offered_supply_types']) == types
    regions=rules_of(result,'applicant_regions')[-1]
    assert scope in [r['region_name'] for r in regions['regions']]
    inventory=public_offered_supplies(result['rules'])
    assert inventory and all(s.supply_count > 0 for s in inventory)
    assert {s.supply_type for s in inventory} == types
    assert all(s.document_hash == by_number(number)['document_hash'] and s.evidence_page and s.criterion_date for s in inventory)
    assert all(not r.get('supply_type') or r['supply_type'] in types for r in result['rules'] if r.get('effect')!='metadata')
    if cap: assert rules_of(result,'price_cap')[-1]['value']==cap

def test_second_round_and_reordered_current_cutoff_keep_original_date_separate():
    row=by_number('2026910251')
    assert document_cutoff(row['pages'],method='unranked_after')[0]=='2026-09-28'
    context=rules_of(parse(row),'qualification_context')[-1]['value']
    assert context['original_announcement_date']=='2026-08-07'
    assert context['application_criterion_date']=='2026-09-28'
    assert all(r['criterion_date']=='2026-10-02' for r in parse(by_number('2026000498'))['rules'])

def test_tang_first_home_income_alternative_and_exclusive_area():
    result=parse(by_number('2026930039'))
    assert result['offered_supply_types']==['생애최초 특별공급']
    assert rules_of(result,'never_owned_home')[0]['exclude_spouse_pre_marriage_disposed'] is True
    financial=next(r for r in rules_of(result,'any') if r.get('label')=='월평균소득 또는 부동산 기준')
    assert financial['conditions'][0]['income_table'][0]['max_krw']==12054021
    assert financial['conditions'][1]['value']==331000000
    assert rules_of(result,'first_home_family')[0]['solo_max_area_sqm']==60
    assert {u['exclusive_area_sqm'] for u in rules_of(result,'unit_exclusive_areas')[0]['units']}=={59.9901,74.8177}

@pytest.mark.parametrize('row',PUBLIC[:3],ids=lambda r:r['external_id'])
def test_reviewed_public_sale_admission_can_be_complete_without_apt_rank(row):
    result=parse(row)
    assert result['status']=='complete'
    assert requirements_complete(result['rules'],False) is True
    assert rules_of(result,'rank_applicability')[0]['status']=='not_applicable'
    assert not rules_of(result,'homeless')  # Explicit homeowner permission.
    assert 'home_ownership' in rules_of(result,'condition_exemptions')[0]['topics']
    assert parse(row,changed=True)['status']=='partial'

def test_contract_date_is_not_replaced_by_announcement_date():
    result=parse(PUBLIC[1])
    context=rules_of(result,'qualification_context')[0]['value']
    assert context['application_criterion_date'] is None and context['application_criterion_basis']=='contract_date'
    assert all(r['criterion_basis']=='contract_date' for r in result['rules'])

def test_employee_clause_reads_the_outcome_not_the_section_title():
    explicit = rules_of(parse(PUBLIC[0]), 'provider_employee_restriction')[0]
    possible = rules_of(parse(PUBLIC[2]), 'provider_employee_restriction')[0]
    assert explicit['restriction_uncertain'] is False
    assert possible['restriction_uncertain'] is True
    assert '제한될 수' in possible['evidence_text']

def test_a17_actual_three_family_routes_shared_by_both_sources():
    lh=parse(PUBLIC[3])
    raw={**PUBLIC[3], 'payload':{**PUBLIC[3]['payload'],'source':'cheongyak_home','category':'apt'}}
    home=parse(raw)
    assert lh['rules']==home['rules']
    assert lh['offered_supply_types']==['신혼부부(신혼희망타운)','예비신혼부부(신혼희망타운)','한부모가족(신혼희망타운)']
    assert not rules_of(lh,'national_rank_months')
    assert len(rules_of(lh,'subscription_months'))==3
    assert all(r['value']==6 for r in rules_of(lh,'recognized_payments_min'))
    assert rules_of(lh,'shinhee_income')[0]['percentage_tables']['200'][0]['max_krw']==15067526
    assert rules_of(lh,'shinhee_assets')[0]['two_children_max_krw']==431000000

def test_suwon_shinhee_residual_does_not_require_six_months_or_income():
    result=parse(PUBLIC[4])
    assert result['offered_supply_types']==['신혼부부(신혼희망타운)','예비신혼부부(신혼희망타운)','한부모가족(신혼희망타운)']
    assert not rules_of(result,'national_rank_months') and not rules_of(result,'subscription_months')
    assert rules_of(result,'application_restriction')[0]['project_id']=='LH-SUWON-DANGSU-A3'

def test_discovery_failure_retains_current_reviewed_facts_and_adds_safe_stage():
    from app.extract.official_rules import PARSER_VERSION
    fact={'kind':'age_min','value':19,'source':'official_document_parser','verification':'official','document_hash':'file','parser_version':PARSER_VERSION}
    current={'source':'lh','external_id':'retained','rules':[fact],'document_hash':'file','category':'public_sale'}
    diagnostic={'kind':'document_diagnostics','effect':'metadata','source':'official_document_parser','verification':'official','document_hash':'file','parser_version':PARSER_VERSION,'diagnostics':[{'stage':'discovery','code':'attachment_not_found'}]}
    patch=_document_patch(current,{**current,'rules':[fact,diagnostic]})
    assert fact in patch['rules'] and diagnostic in patch['rules']

def test_official_lh_download_uses_api_file_id_and_ignores_forms():
    html="<a href=\"javascript:fileDownLoad('12345')\">공고.pdf</a><a href=\"javascript:fileDownLoad('12346')\">신청서.pdf</a>"
    links=find_document_links(html,'https://apply.lh.or.kr/lhapply/notice')
    assert len(links)==1 and '12345' in links[0]

@pytest.mark.parametrize('row',CURRENT_PRIVATE,ids=lambda r:r['external_id'])
def test_remaining_current_private_documents_have_actual_regions_and_stock(row):
    result=parse(row)
    region=[rule for rule in rules_of(result,'applicant_regions') if not rule.get('supply_type')]
    assert len(region)==1
    inventory=public_offered_supplies(result['rules'])
    assert inventory and all(r.supply_count > 0 for r in inventory)
    if row['external_id']=='2026910253':
        assert region[0]['unrestricted'] is True and region[0]['priority_applicable'] is False
        assert rules_of(result,'housing_classification')[0]['housing_kind']=='private'
    else:
        assert {r['region_code'] for r in region[0]['regions']}=={'11','28','41'}
        assert region[0]['exceptions'][0]['residence_area']=='other'
    if row['external_id']=='2026000386':
        assert not any(r.supply_type=='노부모부양 특별공급' for r in inventory)
        assert [r.supply_type for r in inventory if r.unit_type=='074.9936A']==['일반공급']

def test_context_projection_preserves_official_contract_basis_and_compatibility():
    from app.qualification import public_classification
    from app.extract.official_rules import parser_version_usable
    assert public_classification(parse(PUBLIC[1])['rules'])[2].application_criterion_basis=='contract_date'
    old={'source':'official_document_parser','parser_version':'official-sections-2026-10-04-v4','kind':'deposit_min_krw'}
    assert parser_version_usable(old,category='apt')
    assert not parser_version_usable(old,category='unsold')
