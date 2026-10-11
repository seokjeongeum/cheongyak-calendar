"""New identities, pages and printed financial values use the same parser."""
import copy
import hashlib
import json
import re
from pathlib import Path

from app.extract.official_rules import parse_official_rules
from app.extract.generic_admission import REVIEW_VERSION

FIXTURES = Path(__file__).parent / 'fixtures'
SOURCE = next(row for row in json.loads((FIXTURES/'current-oct8-regions.json').read_text()) if row['external_id']=='2026000458')


def parse(row):
    return parse_official_rules(row['pages'], url=row.get('document_url', row.get('url')), digest=row['document_hash'], payload=row['payload'])


def coverage(result):
    return {scope['supply_type']: scope for rule in result['rules'] if rule['kind']=='condition_coverage' for scope in rule['scopes']}


def walk(rules):
    for rule in rules:
        yield rule
        yield from walk(rule.get('conditions', []))


def new_notice():
    row = copy.deepcopy(SOURCE)
    row['payload'].update(title='해오름역 미래주택', announcement_date='2030-09-10',
                          official_url='https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=2030000001&pblancNo=2030000001', rules=[])
    row['document_url']='https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2030000001&pblancNo=2030000001&atchmnflSeqNo=1&atchmnflSn=1'
    for page in row['pages']:
        page['page'] += 5
        page['text'] = page['text'].replace('2026000458','2030000001').replace('2026.10.08','2030.09.10').replace('산곡역자이힐스테이트&하늘채','해오름역 미래주택').replace('산곡역자이힐스테이트앤하늘채','해오름역 미래주택')
    row['document_hash'] = hashlib.sha256(json.dumps(row['pages'], ensure_ascii=False).encode()).hexdigest()
    return row


def test_new_notice_identity_date_hash_and_shifted_pages_do_not_require_catalog_entry():
    result = parse(new_notice())
    scopes = coverage(result)
    assert scopes['일반공급']['complete']
    assert len(scopes)==7 and all(scope['review_version']==REVIEW_VERSION for scope in scopes.values())
    assert all(scope['completion_basis']=='document_structure_reviewed_standard_branch' for scope in scopes.values())
    assert next(rule for rule in result['rules'] if rule['kind']=='overseas_residence')['evidence_page']==8
    assert all(rule.get('criterion_date') in {None,'2030-09-10'} for rule in walk(result['rules']))
    stock = next(rule for rule in result['rules'] if rule['kind']=='offered_supplies')['supplies']
    assert sum(row['supply_count'] for row in stock)==1289


def test_current_printed_financial_amounts_years_and_assets_are_read_without_old_constants():
    row = new_notice()
    for page in row['pages']:
        page['text'] = page['text'].replace('2025년도','2029년도').replace('3억 3,100만원','4억 2,500만원').replace('3억3,100만원','4억2,500만원')
        if any(term in page['text'] for term in ('소득금액','소득기준')):
            page['text'] = re.sub(r'(?<![\d,])([\d,]+)원', lambda m: f'{int(m[1].replace(",", ""))*2:,}원', page['text'])
    result = parse(row)
    financial = next(rule for rule in result['rules'] if rule['kind']=='any' and rule.get('supply_type')=='생애최초 특별공급' and rule.get('label')=='월평균소득 또는 부동산 기준')
    income, asset = financial['conditions']
    assert income['income_table'][0]['max_krw']==24108042
    assert asset['value']==425000000
    scope = next(rule for rule in result['rules'] if rule['kind']=='income_household_scope' and rule.get('supply_type')=='생애최초 특별공급')
    assert scope['income_year']==2029
    assert coverage(result)['생애최초 특별공급']['complete']


def test_changed_current_bank_types_are_not_borrowed_from_other_types():
    row = new_notice()
    for page in row['pages']:
        if '5 일반공급' in page['text']:
            page['text'] = page['text'].replace('2순위 : 예치금액과 관계없이 청약예금·청약부금·주택청약종합저축에 가입한 분','2순위 : 예치금액과 관계없이 주택청약종합저축에 가입한 분')
    result = parse(row)
    general = next(rule for rule in result['rules'] if rule['kind']=='account_type' and rule.get('supply_type')=='일반공급' and rule.get('criterion_basis')=='announcement')
    assert general['allowed_values']==['comprehensive']
    assert 'area_limit_for_installment' not in general
    assert coverage(result)['일반공급']['complete']


def test_actual_head_and_financial_waivers_keep_their_source_table():
    scopes = coverage(parse(new_notice()))
    topics = {topic['topic']: topic for topic in scopes['일반공급']['topics'] if topic['status']=='not_applicable'}
    assert topics['세대주']['waived_rule_kind']=='household_head'
    assert topics['세대주']['evidence_page']==6
    assert topics['소득 기준']['waived_rule_kind']=='monthly_income_max_krw'
    assert not any(t['topic']=='세대주' and t['status']=='not_applicable' for t in scopes['노부모부양 특별공급']['topics'])


def test_new_office_identity_pages_and_adult_value_are_discovered_from_qualification():
    row = json.loads((FIXTURES/'okjung-office-20261008.json').read_text())
    row['payload'].update(title='미래동 오피스텔', announcement_date='2030-09-10', official_url='https://www.applyhome.co.kr/ai/aia/selectPRMOLttotPblancDetailView.do?houseManageNo=2030950011&pblancNo=2030950011', rules=[])
    row['url']='https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2030950011&pblancNo=2030950011&atchmnflSeqNo=2&atchmnflSn=1'
    row['document_hash']='new-independent-office-document'
    for page in row['pages']:
        page['page'] += 9
        page['text']=page['text'].replace('2026.10.08','2030.09.10').replace('19세 이상인 자','21세 이상인 자')
    result = parse(row)
    assert coverage(result)['일반공급']['complete']
    adult = next(rule for rule in result['rules'] if rule['kind']=='age_min')
    assert adult['value']==21 and adult['evidence_page']==16
    region = next(rule for rule in result['rules'] if rule['kind']=='applicant_regions')
    assert region['unrestricted'] and region['scope_complete']


def test_unknown_office_applicant_condition_blocks_complete_without_treating_payment_as_fact():
    row = json.loads((FIXTURES/'okjung-office-20261008.json').read_text())
    page = next(page for page in row['pages'] if page['page']==7)
    page['text'] = page['text'].replace('■ 청약일정 및 장소','• 무주택 상태여야 신청할 수 있으며 소득 요건을 충족해야 합니다.\n■ 청약일정 및 장소')
    result = parse(row)
    assert not coverage(result)['일반공급']['complete']
    assert any('추가 신청 조건' in topic for topic in coverage(result)['일반공급']['missing_topics'])


def test_office_price_table_uses_counts_and_sums_for_new_hash_and_blocks_bad_totals():
    row = next(row for row in json.loads((FIXTURES/'official-rules-v3.json').read_text()) if row['house_manage_no']=='2026950085')
    result = parse_official_rules(row['pages'],url=row['document_url'],digest='new-office-source')
    assert {price['unit_type']:price['amount_krw'] for price in result['prices']}=={'28D':588000000,'36A':819800000,'40B':913810000,'40C':937560000}
    assert all(price['document_hash']=='new-office-source' for price in result['prices'])
    pages = copy.deepcopy(row['pages'])
    pages[1]['text'] = pages[1]['text'].replace('588,000,000','588,000,001',1)
    assert parse_official_rules(pages,url=row['document_url'],digest='contradictory-total')['prices']==[]
