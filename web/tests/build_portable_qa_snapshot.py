"""Build isolated browser replay data from recorded official parser fixtures.

This does not collect live data or access a database. Replay reception dates,
the benchmark project association, and load-test copies are fictional and are
marked in every affected title and in the snapshot provenance. Existing saved
official rule/price/competition evidence is reused without claiming freshness.

Run with the API virtualenv, then pass --snapshot to the browser QA scripts.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'api'))

from app.extract.official_rules import parse_official_rules
from app.ingest.competition import parse_popup
from app.ingest.reb import PAIRS, normalize
from app.ingest.winning_scores import parse_score_popup
from app.qualification import (public_application_method, public_classification,
    public_contract_schedule, public_offered_supplies, public_rank_applicability,
    public_selection_methods, public_winning_scores, requirements_complete)
from app.schemas import NoticePublic

FIXTURES = ROOT / 'api/tests/fixtures'
REGIONAL_TITLES = {
    '2026930038': '고양 장항 제일풍경채 계약취소주택',
    '2026000498': '천안 아이파크 시티 5단지',
    '2026910251': '서울 무순위 공고',
    '2026000444': '제주 민영주택 공고',
    '2026930039': '아산 탕정 푸르지오 계약취소주택',
}


def public_notice(payload, identity):
    """Use the public API field helpers, without a DB or repository writes."""
    rules = payload.get('rules', [])
    kind, kind_evidence, context = public_classification(rules)
    method, method_evidence = public_application_method(rules)
    return NoticePublic(
        id=identity, source=payload.get('source', 'cheongyak_home'),
        sources=[payload.get('source', 'cheongyak_home')],
        provider=payload.get('provider'), title=payload['title'],
        category=payload['category'], housing_kind=kind,
        housing_kind_evidence=kind_evidence, qualification_context=context,
        application_method=method, application_method_evidence=method_evidence,
        rank_applicability=public_rank_applicability(rules),
        contract_schedule=public_contract_schedule(rules),
        offered_supplies=public_offered_supplies(rules),
        selection_methods=public_selection_methods(rules),
        winning_scores=public_winning_scores(rules),
        address=payload.get('address'), region_code=payload.get('region_code'),
        region_name=payload.get('region_name'),
        announcement_date=payload.get('announcement_date'),
        official_url=payload.get('official_url'), document_hash=payload.get('document_hash'),
        price_cap_status=payload.get('price_cap_status', 'unknown'),
        events=payload.get('events', []), prices=[{'source': payload.get('source', 'cheongyak_home'), **p} for p in payload.get('prices', [])],
        competitions=payload.get('competitions', []), competition=payload.get('competition', {}),
        rules=rules, rules_complete=requirements_complete(rules, payload.get('rules_complete', False)),
        updated_at='2026-10-05T00:00:00Z', version=1,
    ).model_dump(mode='json')


def snapshot(today):
    notices = []
    provenance = []
    for name in ['current-private-v5', 'public-v5', 'regional-v5']:
        for raw in json.loads((FIXTURES / (name + '.json')).read_text()):
            number = raw.get('external_id') or raw['house_manage_no']
            payload = copy.deepcopy(raw.get('payload', {}))
            payload.setdefault('title', REGIONAL_TITLES.get(number, '기록 공고'))
            payload.setdefault('category', 'unsold' if number.startswith('20269') else 'apt')
            payload.setdefault('official_url', raw['document_url'])
            parsed = parse_official_rules(raw['pages'], url=raw['document_url'],
                digest=raw['document_hash'], payload=payload)
            payload['rules'] = parsed['rules']
            payload['document_hash'] = raw['document_hash']
            payload['rules_complete'] = parsed['status'] == 'complete'
            context = next((r.get('value', {}) for r in parsed['rules'] if r['kind'] == 'qualification_context'), {})
            payload.setdefault('announcement_date', context.get('application_announcement_date') or context.get('application_criterion_date'))
            cap = next((r.get('value') for r in parsed['rules'] if r['kind'] == 'price_cap'), None)
            if cap in ['yes', 'no']:
                payload['price_cap_status'] = cap
            # These replay windows exercise current/future reception, not the
            # source document's real reception schedule.
            index = len(notices)
            first, last = today + timedelta(days=index % 7), today + timedelta(days=index % 7 + 1)
            if index == 0:
                first = today - timedelta(days=1)
            payload['title'] = '[QA 가상 일정] ' + payload['title']
            payload['events'] = [{'kind': 'general', 'label': 'QA 가상 청약 접수',
                'start_date': first.isoformat(), 'end_date': last.isoformat()}]
            notice = public_notice(payload, 'qa-recorded-' + number)
            notices.append(notice)
            provenance.append({'id': notice['id'], 'fixture': name + '.json',
                'documentHash': raw['document_hash'], 'fictionalReceptionDates': True,
                'freshCollection': False})

    # The recorded official API model fixture supplies real KRW price rows.
    detail = json.loads((FIXTURES / 'jamsil-detail.json').read_text())[0]
    models = json.loads((FIXTURES / 'jamsil-models.json').read_text())
    jamsil = normalize(detail, models, PAIRS[1])
    jamsil['title'] = '[QA 기록 API] ' + jamsil['title']
    notices.append(public_notice(jamsil, 'qa-recorded-jamsil'))
    provenance.append({'id': 'qa-recorded-jamsil', 'fixture': 'jamsil-detail.json + jamsil-models.json',
        'fictionalReceptionDates': False, 'freshCollection': False})

    ongoing = copy.deepcopy(notices[-1])
    ongoing['id'] = 'qa-fictional-open-reception'
    ongoing['title'] = '[QA 가상 상시 접수] 종료일 미공개·기록 가격 재생'
    ongoing['events'] = [{'kind': 'general', 'label': 'QA 가상 상시 접수 · 마감 시 종료일 미공개',
        'start_date': (today - timedelta(days=20)).isoformat(), 'end_date': None}]
    ongoing['application_end_date'] = None
    notices.append(ongoing)
    provenance.append({'id': ongoing['id'], 'fixture': 'jamsil-models.json',
        'fictionalProjectAssociation': True, 'fictionalReceptionDates': True,
        'fictionalEndDate': False, 'freshCollection': False})

    # A synthetic project provides a deliberately unknown automatic region.
    # The recorded table's values are real fixture values; associating them
    # with this synthetic project is only a UI benchmark test.
    benchmark = copy.deepcopy(notices[0])
    benchmark['id'] = 'qa-fictional-manual-benchmark'
    benchmark['title'] = '[QA 가상 사업·가점 비교] 기록 표 재생'
    benchmark['official_url'] = 'https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=QA-BENCHMARK&pblancNo=QA-BENCHMARK'
    benchmark['rules'] = [r for r in benchmark['rules'] if r['kind'] not in ['applicant_regions', 'regional_allocation', 'selection_method', 'offered_supplies', 'unit_exclusive_areas']]
    table_url = 'https://www.applyhome.co.kr/ai/aia/selectAPTCompetitionPopup.do?houseManageNo=QA-BENCHMARK&pblancNo=QA-BENCHMARK'
    observed = datetime(2026, 10, 5, tzinfo=timezone.utc)
    html = (FIXTURES / 'winning-score-public.html').read_text()
    parsed_competition = parse_popup(html, table_url, observed_at=observed)
    scores = parse_score_popup(html, url=table_url, house_no='QA-BENCHMARK',
        notice_no='QA-BENCHMARK', observed_at=observed.isoformat())
    for row in scores:
        row['criterion_date'] = benchmark['qualification_context']['application_criterion_date']
    benchmark['winning_scores'] = scores
    benchmark['competitions'] = [{**r, 'observed_at': r['observed_at'].isoformat()} for r in parsed_competition.rows]
    benchmark['competition'] = {'status': 'success', 'complete': True,
        'unit_types': parsed_competition.unit_types, 'evidence_url': table_url}
    benchmark['offered_supplies'] = [{'supply_type': '일반공급', 'unit_type': s['unit_type'], 'supply_count': 1,
        'verification': 'official', 'evidence_url': table_url} for s in scores]
    benchmark['selection_methods'] = [{'kind': 'selection_method', 'effect': 'metadata',
        'rank': 1, 'unit_types': [s['unit_type'] for s in scores], 'points_percent': 40,
        'lottery_percent': 60, 'verification': 'official', 'evidence_url': table_url}]
    # Preserve actual recorded price rows elsewhere; a fictional benchmark
    # has no invented prices or claim to a source-project price association.
    benchmark['prices'] = []
    benchmark['events'] = [{'kind': 'general', 'label': 'QA 가상 종료 일정',
        'start_date': (today - timedelta(days=10)).isoformat(),
        'end_date': (today - timedelta(days=9)).isoformat()}]
    benchmark = NoticePublic.model_validate(benchmark).model_dump(mode='json')
    provenance.append({'id': benchmark['id'], 'fixture': 'winning-score-public.html',
        'fictionalProjectAssociation': True, 'fictionalReceptionDates': True,
        'fictionalSelectionMethod': True, 'freshCollection': False})
    mismatch = copy.deepcopy(benchmark)
    mismatch['id'] = 'qa-fictional-region-mismatch-result'
    mismatch['title'] = '[QA 가상 지역 불일치 결과] 기록 표 재생'
    regional = next(n for n in notices if n['id'] == 'qa-recorded-2026000444')
    mismatch['rules'].extend(copy.deepcopy([r for r in regional['rules'] if r['kind'] == 'applicant_regions']))
    provenance.append({'id': mismatch['id'], 'fixture': 'regional-v5.json + winning-score-public.html',
        'fictionalProjectAssociation': True, 'fictionalReceptionDates': True,
        'fictionalSelectionMethod': True, 'freshCollection': False})
    current_result = copy.deepcopy(mismatch)
    current_result['id'] = 'qa-fictional-current-competition'
    current_result['title'] = '[QA 가상 현재 경쟁률] 기록 표 재생'
    current_result['events'] = [{'kind': 'general', 'label': 'QA 가상 청약 접수',
        'start_date': today.isoformat(), 'end_date': (today + timedelta(days=2)).isoformat()}]
    notices.append(current_result)
    provenance.append({'id': current_result['id'], 'fixture': 'regional-v5.json + winning-score-public.html',
        'fictionalProjectAssociation': True, 'fictionalReceptionDates': True,
        'fictionalSelectionMethod': True, 'freshCollection': False})
    return {'schedule': notices, 'results': [benchmark, mismatch],
        'coverage': {'sources': [{'source': 'qa_recorded_fixtures', 'status': 'success',
            'message': 'QA 격리 재생 데이터 · 새 공식 수집 아님', 'record_count': len(notices)}]},
        'provenance': {'date': today.isoformat(), 'mode': 'isolated_recorded_fixture_replay',
            'freshLiveCollection': False, 'productionDatabaseTouched': False,
            'fictionalDisplayVariants': True, 'notices': provenance}}


def main(args):
    public = snapshot(date.fromisoformat(args.today))
    if args.count:
        originals = public['schedule']
        copies = []
        for index in range(args.count):
            copy_notice = copy.deepcopy(originals[index % len(originals)])
            copy_notice['id'] += '-load-' + str(index + 1)
            copy_notice['title'] = f'[QA 가상 부하 {index + 1:02d}] ' + copy_notice['title']
            copies.append(copy_notice)
        public['schedule'] = copies
        public['provenance']['fictionalLoadTestNoticeCount'] = args.count
    Path(args.output).write_text(json.dumps(public, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': args.output, 'schedule': len(public['schedule']),
        'results': len(public['results']), 'freshLiveCollection': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--today', default='2026-10-06')
    parser.add_argument('--output', required=True)
    parser.add_argument('--count', type=int, help='Fictional copies for an isolated load test')
    main(parser.parse_args())
