"""Current layout order must not turn application counts into age criteria."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.extract.official_rules import parse_official_rules


SOURCE = json.loads((Path(__file__).parent / 'fixtures' / 'dangsan-office-20261006.json').read_text())


def parse(source):
    return parse_official_rules(source['pages'], url=source['document_url'],
                                digest=source['document_hash'], payload=source['payload'])


def scope(result):
    return next(rule for rule in result['rules'] if rule['kind'] == 'condition_coverage')['scopes'][0]


def qualification_page(source):
    return next(page for page in source['pages'] if '■ 청약자격 및 유의사항' in page['text'])


def test_current_layout_reviews_full_applicant_bullet_and_keeps_procedures_separate():
    assert '1 1 , 2 . • 청약신청은 인당 개실' in qualification_page(SOURCE)['text']
    result = parse(SOURCE)
    assert result['status'] == 'complete'
    assert scope(result)['missing_topics'] == []
    age = next(rule for rule in result['rules'] if rule['kind'] == 'age_min')
    assert age['value'] == 19
    assert '(2026.10.06.) 19' in age['evidence_text']
    assert '외국인 포함' in age['evidence_text'] and '또는 법인의 경우' in age['evidence_text']
    assert not any(rule['kind'] == 'citizenship' for rule in result['rules'])
    instructions = next(rule for rule in result['rules'] if rule['kind'] == 'application_instructions')
    assert all(item['phase'] == 'application' for item in instructions['instructions'])
    assert all(rule['document_hash'] == SOURCE['document_hash'] for rule in result['rules'])


def test_standalone_pdf_section_glyph_does_not_crash_the_whole_document_audit():
    source = copy.deepcopy(SOURCE)
    source['pages'][0]['text'] += '\n■\n'
    result = parse(source)
    assert result['status'] == 'complete'


def test_reordered_values_follow_new_identity_date_age_hash_and_page_positions():
    source = copy.deepcopy(SOURCE)
    source['payload'].update(title='미래역 오피스텔', external_id='2030950099', announcement_date='2030-09-10')
    source['payload']['official_url'] = source['payload']['official_url'].replace('2026950087', '2030950099')
    source['document_url'] = source['document_url'].replace('2026950087', '2030950099')
    for page in source['pages']:
        page['page'] += 11
        page['text'] = page['text'].replace('2026.10.06', '2030.09.10').replace(') 19 [', ') 23 [')
    source['document_hash'] = hashlib.sha256(json.dumps(source['pages'], ensure_ascii=False).encode()).hexdigest()
    result = parse(source)
    assert scope(result)['complete'] is True
    age = next(rule for rule in result['rules'] if rule['kind'] == 'age_min')
    assert age['value'] == 23 and age['evidence_page'] == 15
    assert all(rule['criterion_date'] == '2030-09-10' and rule['document_hash'] == source['document_hash'] for rule in result['rules'])


@pytest.mark.parametrize('placement', ['before', 'after', 'ordered'])
def test_duplicate_application_counts_never_become_competing_age_values(placement):
    source = copy.deepcopy(SOURCE)
    page = qualification_page(source)
    old = '1 1 , 2 . • 청약신청은 인당 개실 청약 가능하며 동일인이 개실 이상 중복 신청하는 경우 청약신청 모두를 무효처리 합니다'
    if placement == 'before':
        new = old.replace('1 1 , 2 .', '7 7 , 8 .')
    elif placement == 'after':
        new = '• 청약신청은 인당 개실 청약 가능하며 동일인이 개실 이상 중복 신청하는 경우 청약신청 모두를 무효처리 합니다 7 7 , 8 .'
    else:
        new = '• 청약신청은 7인당 7개실 청약 가능하며, 동일인이 8개실 이상 중복 신청하는 경우 청약신청 모두를 무효처리 합니다.'
    assert old in page['text']
    page['text'] = page['text'].replace(old, new)
    result = parse(source)
    assert scope(result)['complete'] is True
    assert next(rule for rule in result['rules'] if rule['kind'] == 'age_min')['value'] == 19


@pytest.mark.parametrize('placement', ['applicant', 'procedure', 'separate'])
@pytest.mark.parametrize('unknown,expected', [
    ('자동차가액 4,500만원 이하인 자만 신청 가능합니다.', ['자동차가액', '4,500만원']),
    ('신청자는 무주택세대구성원이어야 합니다.', ['무주택세대구성원']),
])
def test_unknown_mandatory_predicate_retains_specific_gap_after_known_office_clauses(placement, unknown, expected):
    source = copy.deepcopy(SOURCE)
    page = qualification_page(source)
    if placement == 'applicant':
        page['text'] = page['text'].replace('외국인 포함', '외국인 포함, ' + unknown)
    elif placement == 'procedure':
        page['text'] = page['text'].replace('청약신청 모두를 무효처리 합니다', '청약신청 모두를 무효처리 합니다. ' + unknown)
    else:
        page['text'] = page['text'].replace('■ 청약일정 및 장소', '• ' + unknown + '\n■ 청약일정 및 장소')
    result = parse(source)
    assert scope(result)['complete'] is False
    assert any(all(term in topic for term in expected) for topic in scope(result)['missing_topics'])


@pytest.mark.parametrize('replacement', ['', '19 21'])
def test_missing_or_ambiguous_age_is_not_filled_from_application_counts(replacement):
    source = copy.deepcopy(SOURCE)
    page = qualification_page(source)
    page['text'] = page['text'].replace(') 19 [', ') ' + replacement + ' [')
    result = parse(source)
    assert scope(result)['complete'] is False
    assert not any(rule['kind'] == 'age_min' for rule in result['rules'])


def test_date_from_another_bullet_cannot_certify_missing_applicant_cutoff():
    source = copy.deepcopy(SOURCE)
    page = qualification_page(source)
    page['text'] = page['text'].replace('(2026.10.06.) 19', '19')
    page['text'] = page['text'].replace('■ 청약일정 및 장소', '• 참고 날짜 (2026.10.06.)\n■ 청약일정 및 장소')
    assert scope(parse(source))['complete'] is False


@pytest.mark.parametrize('page_number', [1, 11])
@pytest.mark.parametrize('heading', ['■ 별도 신청 제한\n• ', '■ 추가 청약자격\n• ', ''])
@pytest.mark.parametrize('clause,expected', [
    ('신청자는 무주택세대구성원이어야 합니다.', '무주택세대구성원'),
    ('자동차가액 4,500만원 이하인 자만 신청 가능합니다.', '자동차가액'),
])
def test_out_of_section_applicant_restriction_blocks_whole_document_completion(page_number, heading, clause, expected):
    source = copy.deepcopy(SOURCE)
    page = next(page for page in source['pages'] if page['page'] == page_number)
    page['text'] += '\n' + heading + clause
    source['document_hash'] = hashlib.sha256(json.dumps(source['pages'], ensure_ascii=False).encode()).hexdigest()
    result = parse(source)
    assert scope(result)['complete'] is False
    assert any(expected in topic and f'{page_number}쪽' in topic for topic in scope(result)['missing_topics'])
    assert all(rule['document_hash'] == source['document_hash'] for rule in result['rules'])


@pytest.mark.parametrize('heading,clause,expected', [
    ('별도 자격 요건', '무주택세대구성원이어야 합니다.', '무주택세대구성원'),
    ('별도 청약 제한', '재당첨 제한 중인 사람은 청약할 수 없습니다.', '재당첨'),
    ('', '신청자는무주택세대구성원이어야합니다.', '무주택세대구성원'),
    ('', '공급 신청 자는 무주택세대구성원이어야 합니다.', '무주택세대구성원'),
    ('', '신청자에게는 자동차가액 4,500만원 이하 조건이 적용됩니다.', '자동차가액'),
    ('', '신청자는 공급기관의 사전승인을 받아야 합니다.', '사전승인'),
])
def test_out_of_section_pdf_spacing_heading_and_mandatory_forms_remain_specific(heading, clause, expected):
    source = copy.deepcopy(SOURCE)
    source['pages'][0]['text'] += '\n' + ('■ ' + heading + '\n• ' if heading else '') + clause
    source['document_hash'] = 'new-document-with-unreviewed-officetel-clause'
    result = parse(source)
    assert scope(result)['complete'] is False
    assert any(expected in topic for topic in scope(result)['missing_topics'])


def test_out_of_section_heading_continues_to_next_page():
    source = copy.deepcopy(SOURCE)
    source['pages'][0]['text'] += '\n■ 별도 신청 제한'
    source['pages'][1]['text'] = '• 무주택세대구성원이어야 합니다.\n' + source['pages'][1]['text']
    source['document_hash'] = 'new-document-with-continued-office-restriction'
    result = parse(source)
    assert scope(result)['complete'] is False
    assert any('무주택세대구성원' in topic and '2쪽' in topic for topic in scope(result)['missing_topics'])


@pytest.mark.parametrize('placement', ['qualification', 'elsewhere'])
def test_liability_instruction_cannot_swallow_a_new_applicant_requirement(placement):
    source = copy.deepcopy(SOURCE)
    changed = '신청자의 착오로 인해 부적격자로 판명되는 경우, 자동차가액 4,500만원 이하인 자만 신청 가능합니다. 이에 대한 책임은 청약 신청자 본인에게 있습니다.'
    if placement == 'qualification':
        page = qualification_page(source)
        page['text'] = page['text'].replace('■ 청약자격 및 유의사항', '■ 청약자격 및 유의사항\n• ' + changed)
    else:
        source['pages'][0]['text'] += '\n• ' + changed
    source['document_hash'] = 'new-document-with-condition-inside-liability-note'
    result = parse(source)
    assert scope(result)['complete'] is False
    assert any('자동차가액' in topic and '4,500만원' in topic for topic in scope(result)['missing_topics'])
