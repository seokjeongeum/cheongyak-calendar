"""A current whole-source review prevents a duplicate's AI clause resurfacing."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.extract.official_rules import parse_official_rules
from app.qualification import is_metadata
from app.repository import notice_public, upsert_notice
from test_repository_api import db, example_notice


def current_source():
    sources = json.loads((Path(__file__).parent / 'fixtures/official-unranked-current-20261012.json').read_text())
    source = next(item for item in sources if item['house_manage_no'] == '2026910255')
    payload = {**example_notice(), 'title': source['title'], 'category': 'unsold',
               'announcement_date': source['announcement_date'],
               'official_url': 'https://www.applyhome.co.kr/ai/aia/selectAPTRemndrLttotPblancDetailView.do?houseManageNo=' + source['house_manage_no']}
    parsed = parse_official_rules(source['pages'], url=source['document_url'], digest=source['document_hash'], payload=payload)
    assert parsed['status'] == 'complete'
    return {**payload, 'document_hash': source['document_hash'], 'rules': parsed['rules'], 'rules_complete': True}


@pytest.mark.parametrize('case', ['complete', 'partial', 'old_parser', 'other_candidate_hash', 'unidentified_candidate', 'no_admission'])
def test_duplicate_uncertain_clause_retires_only_under_current_same_hash_whole_review(db, case):
    raw = current_source()
    candidate = {'kind': 'unparsed', 'verification': 'ai_unverified', 'source': 'gemini_document',
                 'document_hash': raw['document_hash'], 'text': '미검증 신청자격 후보'}
    if case == 'partial':
        for rule in raw['rules']:
            if rule['kind'] == 'condition_coverage':
                rule['status'] = 'partial'
                rule['scopes'][0].update(complete=False, missing_topics=['미검토 제한'])
    elif case == 'old_parser':
        for rule in raw['rules']:
            rule['parser_version'] = 'official-sections-2026-10-12-v18'
    elif case == 'other_candidate_hash':
        candidate['document_hash'] = 'separate-source-bytes'
    elif case == 'unidentified_candidate':
        candidate.pop('document_hash')
    elif case == 'no_admission':
        raw['rules'] = [rule for rule in raw['rules'] if is_metadata(rule)]
    canonical = upsert_notice(db, raw)
    duplicate = upsert_notice(db, {**raw, 'source': 'myhome', 'external_id': 'OLDER-UNCERTAIN-COPY',
                                  'rules': [candidate], 'rules_complete': False})
    db.commit()
    assert duplicate.duplicate_of_id == canonical.id
    originals = deepcopy(duplicate.revisions[0].payload)
    for detail in (False, True):
        public = notice_public([canonical, duplicate], detail=detail)
        assert any(rule.get('source') == 'gemini_document' for rule in public.rules) is (case != 'complete')
        assert public.rules_complete is (case == 'complete')
    assert duplicate.rules == [candidate]
    assert duplicate.revisions[0].payload == originals
    assert len(duplicate.prices) == len(originals['prices']) == 2
    assert duplicate.version == 1 and len(duplicate.revisions) == 1
