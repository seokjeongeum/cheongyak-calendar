"""Exact current official documents; no geographic/rate legal defaults."""
import copy
import json
from pathlib import Path

from app.extract.official_rules import parse_official_rules
from app.extract.reviewed_sources import reviewed_source_for_document

FIXTURES = Path(__file__).parent / 'fixtures'
SANGOK = next(row for row in json.loads((FIXTURES / 'current-oct8-regions.json').read_text()) if row['external_id'] == '2026000458')
SANGOK = copy.deepcopy(SANGOK)
FEED = json.loads((FIXTURES / 'sangok-current-feed-inventory.json').read_text())
SANGOK['payload']['rules'] = [{'kind': 'offered_supplies', 'effect': 'metadata', 'source': 'cheongyak_home', 'verification': 'official', 'evidence_url': FEED['official_url'], 'supplies': FEED['supplies']}]
DANGSAN = json.loads((FIXTURES / 'dangsan-office-20261006.json').read_text())

def parse(row, **overrides):
    return parse_official_rules(overrides.get('pages', row['pages']), url=row['document_url'],
                               digest=overrides.get('digest', row['document_hash']), payload=overrides.get('payload', row['payload']))

def test_sangok_all_supply_allocations_and_actual_page_end_ratio_table():
    result = parse(SANGOK)
    allocations = {r.get('supply_type') or '일반공급': r for r in result['rules'] if r['kind'] == 'regional_allocation'}
    assert allocations['일반공급']['evidence_page'] == 26
    assert allocations['생애최초 특별공급']['evidence_page'] == 21
    assert allocations['생애최초 특별공급']['selection_order'] == ['소득구분', '지역', '추첨']
    multi = allocations['다자녀가구 특별공급']
    assert multi['evidence_page'] == 14
    assert [(s['percent'], set(s['region_codes'])) for s in multi['regional_shares']] == [(50, {'28'}), (50, {'11', '41'})]
    assert multi['unsuccessful_applicants_advance'] is True
    assert multi['local_priority_in_remaining_quota'] is False
    methods = [r for r in result['rules'] if r['kind'] == 'selection_method']
    assert len(methods) == 2
    assert all(r['points_percent'] == 40 and r['lottery_percent'] == 60 and r['evidence_page'] == 26 for r in methods)
    inventory = next(r['supplies'] for r in result['rules'] if r['kind'] == 'offered_supplies')
    units = {s['unit_type'] for s in inventory if s['supply_type'] == '일반공급' and s['supply_count'] > 0}
    assert set().union(*(set(r['unit_types']) for r in methods)) == units
    assert all(r['document_hash'] == SANGOK['document_hash'] and r['criterion_date'] == '2026-10-08' for r in [*allocations.values(), *methods])


def test_sangok_missing_percentages_do_not_become_default_ratios():
    pages = copy.deepcopy(SANGOK['pages'])
    for page in pages:
        page['text'] = page['text'].replace('40%', '미확보').replace('60%', '미확보')
    assert not any(r['kind'] == 'selection_method' for r in parse(SANGOK, pages=pages)['rules'])


def test_dangsan_current_domestic_adult_scope_with_reordered_pdf_cutoff():
    result = parse(DANGSAN)
    assert result['status'] == 'complete'
    assert len(DANGSAN['pages']) == 11
    kinds = {r['kind']: r for r in result['rules']}
    assert kinds['age_min']['value'] == 19
    assert kinds['domestic_residence']['value'] is True
    assert kinds['applicant_regions']['unrestricted'] is True
    assert kinds['applicant_regions']['scope_complete'] is True
    assert kinds['rank_applicability']['account_required'] is False
    assert all(r['criterion_date'] == '2026-10-06' and r['document_hash'] == DANGSAN['document_hash'] for r in result['rules'])
    assert reviewed_source_for_document(DANGSAN['document_url'], DANGSAN['document_hash'])


def test_dangsan_changed_bytes_or_wrong_notice_cannot_borrow_review():
    assert parse(DANGSAN, digest='0' * 64)['status'] != 'complete'
    payload = {**DANGSAN['payload'], 'official_url': DANGSAN['payload']['official_url'].replace('2026950087', '2026950085')}
    assert parse(DANGSAN, payload=payload)['rules'] == []


def test_focused_retry_preserves_other_same_day_audits_and_runs_once():
    from datetime import date
    from app.extract.pipeline import _with_diagnostics
    from app.extract.reviewed_sources import focused_review_version
    from app.ingest.worker import _failed_document_needs_new_pipeline
    from app.models import Notice
    for fixture in [SANGOK, DANGSAN]:
        payload = fixture['payload']
        row = Notice(source='cheongyak_home', external_id=payload['external_id'], official_url=payload['official_url'], announcement_date=date.fromisoformat(payload['announcement_date']), rules=[])
        assert _failed_document_needs_new_pipeline(row) is True
        row.rules = _with_diagnostics(dict(payload), [], 'complete')['rules']
        assert _failed_document_needs_new_pipeline(row) is False
        assert focused_review_version(payload['official_url'], '2026-10-01') is None
    assert focused_review_version(DANGSAN['payload']['official_url'].replace('2026950087', '2026950086'), '2026-10-07') is None
