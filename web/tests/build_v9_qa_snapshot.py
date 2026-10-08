"""Build v9 isolated browser routes from recorded official source fixtures.

This script never opens a database or collects a live document. Only reception
windows and load copies are fictional; each is identified in its title and
provenance. Admission rules and document hashes come from recorded sources.
"""
from __future__ import annotations

import argparse
import copy
import json
from datetime import date, timedelta
from pathlib import Path

from build_portable_qa_snapshot import FIXTURES, public_notice, snapshot
from app.extract.contract_schedule import parse_lh_detail_contract_schedule
from app.extract.official_rules import parse_official_rules


def source_notice(raw: dict, today: date, index: int) -> tuple[dict, dict]:
    payload = copy.deepcopy(raw['payload'])
    parsed = parse_official_rules(raw['pages'], url=raw['document_url'],
        digest=raw['document_hash'], payload=payload)
    payload.update(rules=parsed['rules'], document_hash=raw['document_hash'],
        rules_complete=parsed['status'] == 'complete')
    payload['title'] = '[QA 가상 일정] ' + payload['title']
    payload['events'] = [{'kind': 'general', 'label': 'QA 가상 청약 접수',
        'start_date': (today - timedelta(days=1)).isoformat(),
        'end_date': (today + timedelta(days=index + 2)).isoformat()}]
    notice = public_notice(payload, 'qa-recorded-' + raw['external_id'])
    return notice, {'id': notice['id'], 'documentHash': raw['document_hash'],
        'documentUrl': raw['document_url'], 'recordedPageCount': len(raw['pages']),
        'fictionalReceptionDates': True, 'freshCollection': False}


def v9_snapshot(today: date) -> dict:
    public = snapshot(today)
    sources = [json.loads((FIXTURES / name).read_text()) for name in
        ['gajeong-admission-v8.json', 'hyangnam-regional-v9.json']]
    sources.extend(json.loads((FIXTURES / 'current-regional-v9.json').read_text()))
    replacing = {'qa-recorded-' + raw['external_id'] for raw in sources}
    public['schedule'] = [n for n in public['schedule'] if n['id'] not in replacing]
    public['provenance']['notices'] = [p for p in public['provenance']['notices'] if p['id'] not in replacing]
    for index, raw in enumerate(sources):
        notice, provenance = source_notice(raw, today, index)
        public['schedule'].append(notice)
        public['provenance']['notices'].append(provenance)
    detail = json.loads((FIXTURES / 'gyeongsan-contract-detail-v9.json').read_text())
    contract = parse_lh_detail_contract_schedule(detail['html_fragment'],
        url=detail['official_url'], external_id=detail['external_id'])
    assert contract and contract['start_date'] == '2026-10-27' and contract['end_date'] == '2027-08-31'
    gyeongsan = next(n for n in public['schedule'] if n['id'] == 'qa-recorded-' + detail['external_id'])
    gyeongsan['rules'].append(contract)
    # The same helper serves list/detail API serialization.
    from app.qualification import public_contract_schedule
    gyeongsan['contract_schedule'] = public_contract_schedule(gyeongsan['rules']).model_dump(mode='json')
    gyeongsan['events'] = [{'kind': 'general', 'label': 'QA 가상 청약 접수',
        'start_date': (today - timedelta(days=1)).isoformat(),
        'end_date': (today + timedelta(days=25)).isoformat()}]
    public['provenance']['notices'].append({'id': gyeongsan['id'],
        'fixture': 'gyeongsan-contract-detail-v9.json', 'officialContractPeriod': True,
        'recordedSourceHash': detail['source_hash'], 'evidenceUrl': detail['official_url'],
        'freshCollection': False})
    public['provenance'].update(version=9, sourceDate='2026-10-07',
        productionDatabaseTouched=False, personalProfileIncluded=False)
    public['coverage']['sources'][0]['record_count'] = len(public['schedule'])
    return public


def main(args):
    public = v9_snapshot(date.fromisoformat(args.today))
    if args.count:
        originals = public['schedule']
        public['schedule'] = []
        for index in range(args.count):
            notice = copy.deepcopy(originals[index % len(originals)])
            notice['id'] += '-load-' + str(index + 1)
            notice['title'] = f'[QA 가상 부하 {index + 1:02d}] ' + notice['title']
            public['schedule'].append(notice)
        public['provenance']['fictionalLoadTestNoticeCount'] = args.count
    Path(args.output).write_text(json.dumps(public, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': args.output, 'schedule': len(public['schedule']),
        'recordedSourceCount': len(public['provenance']['notices']),
        'productionDatabaseTouched': False, 'personalProfileIncluded': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--today', default='2026-10-07')
    parser.add_argument('--output', required=True)
    parser.add_argument('--count', type=int)
    main(parser.parse_args())
