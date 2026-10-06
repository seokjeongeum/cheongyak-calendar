import copy
import json
from pathlib import Path
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.ingest.common import FeedError
from app.db import make_engine, init_db, get_session
from app.main import app
from app.repository import upsert_notice, notice_public, related_notices
from app.extract.official_rules import parse_official_rules
from app.extract.selection_rules import parse_selection_rules
from app.ingest.winning_scores import parse_score_popup, collect_winning_scores, record_winning_scores

ROOT = Path(__file__).parent / 'fixtures'


def test_real_private_selection_table_matches_only_positive_general_models():
    rows = json.loads((ROOT/'current-private-v5.json').read_text())
    for raw in rows:
        p = parse_official_rules(raw['pages'],url=raw['document_url'],digest=raw['document_hash'],payload=raw['payload'])
        methods = [r for r in p['rules'] if r['kind']=='selection_method']
        if raw['external_id']=='2026910253':
            assert methods == []  # Unranked has no first-rank points route.
            continue
        assert methods
        general = {s['unit_type'] for r in p['rules'] if r['kind']=='offered_supplies' for s in r['supplies'] if s['supply_type']=='일반공급' and s['supply_count']>0}
        assert {u for m in methods for u in m['unit_types']} == general
        assert all(m['points_percent']+m['lottery_percent']==100 and m['document_hash']==raw['document_hash'] and m['evidence_page'] for m in methods)
        assert all(m['points_percent'] in [0,40] for m in methods)


def test_split_pdf_cells_keep_jeju_cheonan_percentages_and_a17_quotas_separate():
    for raw in json.loads((ROOT/'regional-v5.json').read_text()):
        if raw['house_manage_no'] not in ['2026000444','2026000498']:
            continue
        parsed=parse_official_rules(raw['pages'],url=raw['document_url'],digest=raw['document_hash'])
        methods=[r for r in parsed['rules'] if r['kind']=='selection_method']
        assert methods and all(r['points_percent']==40 and r['lottery_percent']==60 for r in methods)
        allocations=[r for r in parsed['rules'] if r['kind']=='regional_allocation']
        assert allocations[0]['allocation_method']=='region_priority'
        assert allocations[0]['local_share_percent'] is None  # Not an assumed 100% quota.
    raw=next(r for r in json.loads((ROOT/'public-v5.json').read_text()) if r['external_id']=='0000061179')
    parsed=parse_official_rules(raw['pages'],url=raw['document_url'],digest=raw['document_hash'],payload=raw['payload'])
    allocation=next(r for r in parsed['rules'] if r['kind']=='regional_allocation')
    assert allocation['regional_shares']==[{'residence_area':'local','percent':50},{'residence_area':'other','percent':50}]
    assert allocation['supply_type'] is None and '일반공급' not in allocation['supply_types']
    assert not any(r['kind']=='selection_method' for r in parsed['rules'])


@pytest.mark.parametrize('points,lottery', [(100,0),(40,60),(0,100)])
def test_percentages_require_real_columns_and_exclusive_area(points,lottery):
    rules=[{'kind':'housing_classification','verification':'official','housing_kind':'private','criterion_date':'2026-10-02'},{'kind':'offered_supplies','verification':'official','supplies':[{'unit_type':'84A','supply_type':'일반공급','supply_count':1}]},{'kind':'unit_exclusive_areas','verification':'official','units':[{'unit_type':'84A','exclusive_area_sqm':84.99}]}]
    text=f'전용면적별 1순위 가점제/추첨제 적용비율 구분 가점제 추첨제 전용면적 60㎡ 초과 85㎡ 이하 {points}% {lottery}% - 가점 산정기준'
    parsed=parse_selection_rules([{'page':1,'text':text}],url='https://official.example/file',digest='file',rules=rules,parser_version='test')
    assert parsed[0]['points_percent']==points and parsed[0]['lottery_percent']==lottery
    assert parse_selection_rules([{'page':1,'text':text}],url='https://official.example/file',digest='file',rules=rules[:-1],parser_version='test')==[]
    assert parse_selection_rules([{'page':1,'text':text.replace('추첨제 적용비율','지역 적용비율')}],url='https://official.example/file',digest='file',rules=rules,parser_version='test')==[]


def test_existing_api_classification_does_not_drop_selection_on_reprocessing():
    raw=next(r for r in json.loads((ROOT/'current-private-v5.json').read_text()) if r['external_id']=='2026000468')
    payload={**raw['payload'], 'rules':[{'kind':'housing_classification','housing_kind':'private','verification':'official','source':'cheongyak_home'}]}
    result=parse_official_rules(raw['pages'],url=raw['document_url'],digest=raw['document_hash'],payload=payload)
    assert not any(r['kind']=='housing_classification' for r in result['rules'])
    methods=[r for r in result['rules'] if r['kind']=='selection_method']
    assert methods and {r['points_percent'] for r in methods}=={0,40}


def test_coordinate_layout_uses_only_current_official_area_provenance(monkeypatch):
    import app.extract.official_rules as module
    text='전용면적별 1순위 가점제/추첨제 적용비율 구분 가점제 추첨제 전용면적 60㎡ 초과 85㎡ 이하 40% 60% - 가점 산정기준'
    def base(*args, **kwargs):
        return {'rules':[{'kind':'age_min','housing_kind':'private','verification':'official','criterion_date':'2026-10-02'},{'kind':'offered_supplies','verification':'official','supplies':[{'unit_type':'084.9999A','supply_type':'일반공급','supply_count':3}]}]}
    monkeypatch.setattr(module,'_parse_official_rules',base)
    area={'kind':'unit_exclusive_areas','verification':'official','source':'cheongyak_home','units':[{'unit_type':'84.9999A','exclusive_area_sqm':84.99}]}
    def parse(rule):
        return module.parse_official_rules([{'page':4,'text':text}],url='https://official.example/file',digest='current',payload={'rules':[rule]})
    assert next(r for r in parse(area)['rules'] if r['kind']=='selection_method')['unit_types']==['084.9999A']
    for source,digest,verification in [('official_document_parser','old','official'),('cheongyak_home','current','ai_unverified')]:
        assert not any(r['kind']=='selection_method' for r in parse({**area,'source':source,'document_hash':digest,'verification':verification})['rules'])


def test_real_public_result_scores_read_only_first_rank_matching_regions():
    html=(ROOT/'winning-score-public.html').read_text()
    rows=parse_score_popup(html,url='https://www.applyhome.co.kr/official',house_no='example',notice_no='example',observed_at='2026-10-05T00:00:00Z')
    assert rows
    assert rows[0]['min_score']==37 and rows[0]['max_score']==60 and rows[0]['average_score']==42.79
    assert all(r['rank']==1 and r['selection_path']=='points' and r['document_hash'] for r in rows)
    with pytest.raises(FeedError):
        parse_score_popup(html.replace('id="compitTbl"','id="sample"'),url='https://example',house_no='a',notice_no='a',observed_at='now')


@pytest.mark.parametrize('old,new', [
    ('class="cpHouseTy"', 'class="unrecognized"'),
    ('class="cpSubscrptRt"', 'class="unrecognized"'),
    ('>1순위<', '>2순위<'),
    ('data-sem="해당지역"', 'data-sem="기타지역"'),
])
def test_score_popup_requires_matching_official_row_identity(old, new):
    html=(ROOT/'winning-score-public.html').read_text().replace(old,new)
    rows=parse_score_popup(html,url='https://www.applyhome.co.kr/official',house_no='example',notice_no='example',observed_at='2026-10-05T00:00:00Z')
    assert rows == []


@pytest.mark.asyncio
async def test_winning_score_api_auth_failure_falls_back_to_public_table():
    html=(ROOT/'winning-score-public.html').read_text()
    calls=[]
    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(401,json={'message':'Unauthorized'}) if '/api/' in request.url.path else httpx.Response(200,text=html)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        rows,status=await collect_winning_scores(client,'private-key','example','example')
    assert rows and status=='fallback' and len(calls)==2
    assert 'private-key' not in json.dumps(rows)


@pytest.mark.asyncio
@pytest.mark.parametrize('raw', [None, {'HOUSE_MANAGE_NO':'foreign','PBLANC_NO':'example'}])
async def test_malformed_or_foreign_score_api_rows_use_official_popup(raw):
    html=(ROOT/'winning-score-public.html').read_text()
    calls=[]
    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(200,json={'data':[raw]}) if '/api/' in request.url.path else httpx.Response(200,text=html)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        rows,status=await collect_winning_scores(client,'private-key','example','example')
    assert rows and status=='fallback' and len(calls)==2
    assert {r['house_manage_no'] for r in rows} == {'example'}
    assert 'private-key' not in json.dumps(rows)


@pytest.mark.asyncio
async def test_score_api_exact_full_page_uses_match_count():
    pages=[]
    def handle(request):
        pages.append(int(request.url.params['page']))
        return httpx.Response(200,json={'matchCount':100,'data':[{
            'HOUSE_MANAGE_NO':'123','PBLANC_NO':'123','HOUSE_TY':'84A','RESIDE_SECD':'01',
            'LWET_SCORE':37,'TOP_SCORE':60,'AVRG_SCORE':42.79,
        }]*100})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        rows,status=await collect_winning_scores(client,'key','123','123')
    assert len(rows)==100 and status=='success' and pages==[1]


@pytest.mark.asyncio
async def test_api_blank_score_is_unpublished_not_zero_and_keeps_identity():
    def handle(request):
        return httpx.Response(200,json={'data':[{'HOUSE_MANAGE_NO':'123','PBLANC_NO':'123','HOUSE_TY':'84A','RESIDE_SECD':'01','LWET_SCORE':'-','TOP_SCORE':'-','AVRG_SCORE':'-'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        rows,status=await collect_winning_scores(client,'key','123','123')
    assert rows==[] and status=='unpublished'


def test_api_contract_preserves_notice_prices_and_retains_failed_score_evidence(tmp_path):
    engine=make_engine(f'sqlite:///{tmp_path}/scores.db');init_db(engine)
    with sessionmaker(bind=engine,expire_on_commit=False)() as s:
        n=upsert_notice(s,{'source':'cheongyak_home','external_id':'test','title':'공식 점수 검증','category':'apt','official_url':'https://official.example','announcement_date':'2026-10-02','prices':[{'unit_type':'84A','price_kind':'sale_max','amount_krw':100000000,'verification':'official'}],'rules':[]})
        s.commit()
        rows=[{'unit_type':'84A','residence_area':'local','min_score':42,'verification':'official'}]
        record_winning_scores(s,n.id,rows,'success',expected_version=n.version,criterion_date='2026-10-02');s.commit()
        record_winning_scores(s,n.id,[],'error',expected_version=n.version,criterion_date='2026-10-02');s.commit()
        public=notice_public(related_notices(s,n))
        assert public.prices[0].amount_krw==100000000
        assert public.winning_scores[0]['min_score']==42 and public.winning_scores[0]['collection_status']=='error'
        assert public.selection_methods==[]
        record_winning_scores(s,n.id,[],'unpublished',expected_version=n.version-1,criterion_date='2026-10-02');s.commit()
        assert notice_public(related_notices(s,n)).winning_scores
    engine.dispose()


def test_list_and_detail_merge_selection_scores_without_losing_prices(tmp_path):
    engine=make_engine(f'sqlite:///{tmp_path}/merged-selection.db');init_db(engine)
    with sessionmaker(bind=engine,expire_on_commit=False)() as session:
        base={'external_id':'same-offer','title':'공식 선정표 대조','category':'apt','address':'서울특별시 예시 1',
              'announcement_date':'2026-10-02','official_url':'https://official.example',
              'events':[{'kind':'general','label':'일반공급','start_date':'2026-10-07'}],
              'prices':[{'unit_type':'84A','price_kind':'sale_max','amount_krw':100000000,'verification':'official'}]}
        primary=upsert_notice(session,{**base,'source':'myhome'})
        method={'kind':'selection_method','effect':'metadata','verification':'official','source':'cheongyak_home',
                'unit_types':['84A'],'supply_type':'일반공급','rank':1,'points_percent':40,'lottery_percent':60,
                'criterion_date':'2026-10-02','evidence_url':'https://official.example','document_hash':'score-document'}
        secondary=upsert_notice(session,{**base,'source':'cheongyak_home','rules':[method]})
        session.commit()
        assert secondary.duplicate_of_id==primary.id
        record_winning_scores(session,secondary.id,[{'unit_type':'84A','residence_area':'local','min_score':37,
            'verification':'official','house_manage_no':'123','notice_no':'123','supply_type':'일반공급','rank':1,
            'selection_path':'points','evidence_url':'https://official.example'}],'success',
            expected_version=secondary.version,criterion_date='2026-10-02')
        session.commit()
        def override_session():
            yield session
        app.dependency_overrides[get_session]=override_session
        try:
            client=TestClient(app)
            listing=client.get('/api/notices',params={'start':'2026-10-01','end':'2026-10-31'}).json()
            assert listing['total']==1
            card=listing['items'][0]
            for notice_id in (primary.id,secondary.id):
                detail=client.get(f'/api/notices/{notice_id}').json()
                assert card['selection_methods']==detail['selection_methods']==[method]
                assert card['winning_scores']==detail['winning_scores']
                assert detail['winning_scores'][0]['min_score']==37
                assert detail['id']==card['id']==primary.id
                assert detail['prices'][0]['amount_krw']==100000000
        finally:
            app.dependency_overrides.clear()
    engine.dispose()
