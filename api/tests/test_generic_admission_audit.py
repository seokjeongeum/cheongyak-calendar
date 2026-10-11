"""Adversarial new clauses must never inherit the prior template's values."""
import copy
import json
from pathlib import Path

import pytest

from app.extract.generic_admission import _income_extension
from app.extract.official_rules import parse_official_rules

FIXTURES = Path(__file__).parent / 'fixtures'
SOURCE = next(row for row in json.loads((FIXTURES / 'current-oct8-regions.json').read_text())
              if row['external_id'] == '2026000458')
API_CELLS = json.loads((FIXTURES / 'sangok-current-six-feed.json').read_text())['supplies']


def parse(pages, supplied=None):
    payload = copy.deepcopy(SOURCE['payload'])
    payload['rules'] = [{'kind': 'offered_supplies', 'verification': 'official', 'source': 'source_api',
                         'supplies': copy.deepcopy(API_CELLS if supplied is None else supplied)}]
    return parse_official_rules(pages, url=SOURCE['document_url'], digest='new-source-copy', payload=payload)


def scopes(result):
    coverage = next(rule for rule in result['rules'] if rule['kind'] == 'condition_coverage')
    return {scope['supply_type']: scope for scope in coverage['scopes']}


def extension_rows(last=7, base=10000000):
    return {percent: {'table': [{'household_size': last, 'max_krw': base * percent // 100}]}
            for percent in (100, 140, 160)}


def formula(start=8, offset=7, basis=500000):
    return [{'page': 35, 'text': f'{start}인 이상 가구 소득기준: 1인당 평균소득 ({basis:,}) 추가, N-{offset}'}]


def test_income_extension_follows_current_last_size_and_formula_not_eight_person_constant():
    actual = _income_extension(formula(), percent=160, rows=extension_rows())
    assert actual['extra_person_formula_verified'] is True
    assert actual['extra_person_base_krw'] == 500000
    assert actual['extra_person_krw'] == 800000
    assert actual['extra_person_income_base_last_krw'] == 10000000
    assert actual['extra_person_evidence_page'] == 35


@pytest.mark.parametrize('start,offset', [(9, 7), (8, 8), (7, 7)])
def test_income_extension_rejects_threshold_or_subtraction_different_from_printed_last_row(start, offset):
    actual = _income_extension(formula(start, offset), percent=160, rows=extension_rows())
    assert actual['extra_person_formula_verified'] is False
    assert 'extra_person_base_krw' not in actual


def test_conflicting_formula_and_inconsistent_percentages_cannot_supply_extrapolation():
    assert _income_extension(formula() + formula(basis=600000), percent=160, rows=extension_rows())['extra_person_formula_verified'] is False
    values = extension_rows()
    values[140]['table'][-1]['max_krw'] += 1000
    assert _income_extension(formula(), percent=160, rows=values)['extra_person_formula_verified'] is False


@pytest.mark.parametrize('unknown', [
    '■ 청약신청자는 자동차 평가액이 1천만원 이하이어야 합니다.\n■ 순위별 청약통장 자격요건을 만족하는 분',
    '■ 순위별 청약통장 자격요건을 만족하고 자동차 평가액이 1천만원 이하이어야 합니다.',
])
def test_unknown_mandatory_clause_alone_or_after_known_bank_clause_blocks_general_completion(unknown):
    pages = copy.deepcopy(SOURCE['pages'])
    page = next(page for page in pages if '5 일반공급' in page['text'])
    page['text'] = page['text'].replace('■ 순위별 청약통장 자격요건을 만족하는 분', unknown)
    assert not scopes(parse(pages))['일반공급']['complete']


@pytest.mark.parametrize('clause', ['2세 미만', '무주택세대구성원'])
def test_missing_newborn_age_or_housing_clause_leaves_its_own_branch_incomplete(clause):
    pages = copy.deepcopy(SOURCE['pages'])
    page = next(page for page in pages if '신생아 특별공급 (' in page['text'])
    assert clause in page['text']
    page['text'] = page['text'].replace(clause, '조건 미확보')
    assert not scopes(parse(pages))['신생아 특별공급']['complete']


def test_conflicting_current_api_and_pdf_stock_never_certify_any_offered_route():
    cells = copy.deepcopy(API_CELLS)
    cells[0]['supply_count'] += 1
    result = parse(SOURCE['pages'], cells)
    assert all(not scope['complete'] for scope in scopes(result).values())
    assert any(rule.get('inventory_status') == 'conflict' for rule in result['rules'] if rule['kind'] == 'offered_supplies')


@pytest.mark.parametrize('inside_baseline', [False, True])
def test_unknown_office_eligibility_predicate_is_rejected_without_known_fact_nouns(inside_baseline):
    source = json.loads((FIXTURES / 'okjung-office-20261008.json').read_text())
    pages = copy.deepcopy(source['pages'])
    page = next(page for page in pages if page['page'] == 7)
    if inside_baseline:
        page['text'] = page['text'].replace('또는 법인의 경우 신청 가능합니다.',
            '자동차가액 4,500만원 이하인 자만 신청 가능합니다.')
    else:
        page['text'] = page['text'].replace('■ 청약일정 및 장소',
            '• 자동차가액 4,500만원 이하인 자만 신청 가능합니다.\n■ 청약일정 및 장소')
    result = parse_official_rules(pages, url=source['url'], digest='new-office-vehicle-criterion', payload=source['payload'])
    scope = scopes(result)['일반공급']
    assert not scope['complete']
    assert any('자동차가액' in topic and '4,500만원' in topic for topic in scope['missing_topics'])


@pytest.mark.parametrize('date_suffix', ['', '.'])
def test_simple_current_office_baseline_keeps_positive_completion_with_date_punctuation(date_suffix):
    source = json.loads((FIXTURES / 'okjung-office-20261008.json').read_text())
    pages = copy.deepcopy(source['pages'])
    page = next(page for page in pages if page['page'] == 7)
    start = page['text'].index('• 금회 분양광고일')
    stop = page['text'].index('• 청약신청은', start)
    page['text'] = page['text'][:start] + (
        f'• 본 오피스텔의 분양광고일(2027.01.03{date_suffix}) 현재 대한민국에 거주하는 만 19세 이상인 자는 청약 신청 가능합니다.\n'
    ) + page['text'][stop:]
    for candidate in pages:
        candidate['text'] = candidate['text'].replace('2026.10.08', '2027.01.03')
    payload = {**source['payload'], 'announcement_date': '2027-01-03'}
    result = parse_official_rules(pages, url=source['url'], digest='new-office-date-punctuation', payload=payload)
    assert scopes(result)['일반공급']['complete']
    assert next(rule for rule in result['rules'] if rule['kind'] == 'age_min')['criterion_date'] == '2027-01-03'


def test_unknown_predicate_inside_known_children_parenthesis_remains_unreviewed():
    pages = copy.deepcopy(SOURCE['pages'])
    page = next(page for page in pages if '만19세 미만의 자녀 2명 이상(태아, 입양자녀 포함)' in page['text'])
    page['text'] = page['text'].replace('만19세 미만의 자녀 2명 이상(태아, 입양자녀 포함)',
        '만19세 미만의 자녀 2명 이상(태아 포함, 신청자의 자동차가액 4,500만원 이하인 자만 신청 가능합니다)')
    scope = scopes(parse(pages))['다자녀가구 특별공급']
    assert not scope['complete']
    assert any('자동차가액' in topic and '4,500만원' in topic for topic in scope['missing_topics'])
