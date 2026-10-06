"""Official figures never imply local closure without explicit result evidence."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.db import get_session, init_db, make_engine
from app.ingest import competition
from app.ingest.common import FeedError
from app.main import app
from app.models import CompetitionRevision, Notice, SourceStatus
from app.repository import notice_public, record_competition_result, related_notices, upsert_notice

FIXTURES = Path(__file__).parent / "fixtures"
LOCAL_UNITS = ["059.9442A", "059.9442B", "059.9293C", "074.9610"]
NOW = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)


def fixture(no="2026000399"):
    return (FIXTURES / f"competition-{no}.html").read_text()


def popup(no="2026000399"):
    return f"{competition.POPUP_URL}?houseManageNo={no}&pblancNo={no}"


@pytest.fixture()
def factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'competition.db'}")
    init_db(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def payload(no="2026000399", *, source="cheongyak_home", first="2026-09-30"):
    return {
        "source": source, "external_id": f"getAPTLttotPblancDetail:{no}:{no}",
        "title": "공식 경쟁률 검증 아파트", "category": "apt",
        "address": f"서울특별시 예시 {no}", "announcement_date": "2026-09-28",
        "official_url": f"https://official.example/notice/{no}",
        "events": [
            {"kind": "first_priority", "label": "1순위", "start_date": first, "audience": "해당지역"},
            {"kind": "first_priority", "label": "1순위", "start_date": "2026-10-01", "audience": "기타지역"},
        ],
        "prices": [{"unit_type": unit, "price_kind": "sale_max", "amount_krw": 400_000_000, "verification": "official"} for unit in LOCAL_UNITS],
    }


def test_real_local_closed_results_preserve_all_units_regions_and_raw_figures():
    parsed = competition.parse_popup(fixture(), popup(), expected_unit_types=LOCAL_UNITS, observed_at=NOW)
    assert parsed.complete
    assert len(parsed.rows) == 16
    assert parsed.unit_types == LOCAL_UNITS
    first = parsed.rows[0]
    assert (first["unit_type"], first["rank"], first["residence_area"]) == ("059.9442A", 1, "local")
    assert (first["supply_count"], first["application_count"], first["competition_rate"]) == (7, 481, "68.71")
    assert first["result_status"] == "local_first_closed"
    assert parsed.rows[1]["competition_rate"] == "-"
    assert all(row["evidence_url"] == popup() and row["observed_at"] == NOW for row in parsed.rows)


def test_real_generic_first_closed_high_rate_and_shortage_are_not_local_closed():
    parsed = competition.parse_popup(fixture("2026000453"), popup("2026000453"))
    local = {row["unit_type"]: row for row in parsed.rows if row["rank"] == 1 and row["residence_area"] == "local"}
    assert local["059.9742A"]["competition_rate"] == "3.60"
    assert local["059.9742A"]["result_status"] == "first_closed"
    assert local["059.7421B"]["competition_rate"] == "1.10"
    assert local["059.7421B"]["result_status"] == "open"
    assert local["084.8481A"]["competition_rate"] == "(△57)"
    assert local["084.8481A"]["application_count"] == 3
    assert local["084.8481A"]["result_status"] == "open"
    assert not any(row["result_status"] == "local_first_closed" for row in parsed.rows)


@pytest.mark.parametrize("text,expected", [
    ("1순위 해당지역 마감(청약 접수 종료)", "local_first_closed"),
    ("1순위\n 해당지역 마감 ( 청약 접수 종료 )", "local_first_closed"),
    ("1순위 마감(청약 접수 종료)", "first_closed"),
    ("1순위 해당지역 마감 예정", "unknown"),
    ("해당지역 접수 7건 / 공급 7세대", "unknown"),
    ("청약 접수중", "open"),
])
def test_only_explicit_exact_result_establishes_local_closure(text, expected):
    assert competition.result_status(text) == expected


def test_templates_outside_result_table_and_incomplete_unit_inventory_cannot_close():
    text = '<table><tbody><tr><td>1순위 해당지역 마감(청약 접수 종료)</td></tr></tbody></table>'
    with pytest.raises(FeedError):
        competition.parse_popup(text, popup())
    parsed = competition.parse_popup(text + fixture("2026000453"), popup(), expected_unit_types=LOCAL_UNITS)
    assert not parsed.complete
    assert not any(row["result_status"] == "local_first_closed" for row in parsed.rows)
    truncated_inventory = competition.parse_popup(fixture(), popup(), expected_unit_types=LOCAL_UNITS + ["084.0000A"])
    assert not truncated_inventory.complete
    missing_other = fixture().replace('data-sem="기타지역"', 'data-sem="기타오류지역"').replace('<td>기타지역</td>', '<td>기타오류지역</td>')
    assert not competition.parse_popup(missing_other, popup(), expected_unit_types=LOCAL_UNITS).complete


def test_layout_or_unit_identity_changes_fail_closed():
    with pytest.raises(FeedError, match="열 구조"):
        competition.parse_popup(fixture().replace('class="cpSubscrptRt"', 'class="changed"'), popup())
    with pytest.raises(FeedError, match="주택형 식별"):
        competition.parse_popup(fixture().replace('data-ty="0599442A"', 'data-ty="0840000A"', 1), popup())


@pytest.mark.asyncio
async def test_api_uses_documented_filters_match_count_pagination_and_raw_zero():
    pages = []
    def handler(request):
        assert request.url.params["cond[HOUSE_MANAGE_NO::EQ]"] == "1"
        assert request.url.params["cond[PBLANC_NO::EQ]"] == "2"
        assert request.url.params["perPage"] == "100"
        page = int(request.url.params["page"])
        pages.append(page)
        n = 100 if page == 1 else 1
        return httpx.Response(200, json={"matchCount": 101, "totalCount": 900000, "data": [
            {"HOUSE_MANAGE_NO": "1", "PBLANC_NO": "2", "HOUSE_TY": "059.9442A", "MODEL_NO": "01",
             "SUBSCRPT_RANK_CODE": 1, "RESIDE_SECD": "03", "RESIDE_SENM": "기타경기",
             "SUPLY_HSHLDCO": 7, "REQ_CNT": "7", "CMPET_RATE": 0} for _ in range(n)
        ]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await competition.collect_api(client, "private-key", "getAPTLttotPblancCmpet", "1", "2", NOW)
    assert pages == [1, 2]
    assert len(rows) == 101
    assert rows[0]["residence_area"] == "other_gyeonggi"
    assert rows[0]["competition_rate"] == "0"
    assert all(row["result_status"] == "unknown" and "private-key" not in row["evidence_url"] for row in rows)


def test_private_rental_allocations_and_urban_resident_priority_are_not_apt_ranks():
    rental = competition.normalize_api_row({"HOUSE_TY": "59A", "SUPLY_HSHLDCO": 100,
        "SPSPLY_KND_HSHLDCO": 30, "SPSPLY_KND_CODE": "SN", "SPSPLY_KND_NM": "신혼부부",
        "REQ_CNT": "60", "CMPET_RATE": "2.00"}, "getPblPvtRentLttotPblancCmpet", "https://official.example", NOW)
    assert rental["supply_type"] == "newlywed" and rental["supply_type_label"] == "신혼부부"
    assert rental["supply_count"] == 30 and rental["rank"] is None and rental["residence_area"] == "unknown"
    urban = competition.normalize_api_row({"HOUSE_TY": "84A", "RESIDNT_PRIOR_AT": "Y",
        "RESIDNT_PRIOR_SENM": "거주자 우선"}, "getUrbtyOfctlLttotPblancCmpet", "https://official.example", NOW)
    assert urban["resident_priority"] == "Y" and urban["residence_area_label"] == "거주자 우선"
    assert urban["rank"] is None and urban["residence_area"] == "unknown"


@pytest.mark.asyncio
async def test_api_401_falls_back_once_for_multiple_apt_notices_without_secret(factory, monkeypatch):
    monkeypatch.setattr(competition, "SessionLocal", factory)
    monkeypatch.setattr(competition, "init_db", lambda: None)
    monkeypatch.setenv("CHEONGYAK_COMPETITION_API_KEY", "do-not-expose-this-key")
    with factory() as session:
        upsert_notice(session, payload())
        upsert_notice(session, payload("2026000400"))
        session.commit()
    calls = {"api": 0, "popup": 0}
    def handler(request):
        if request.url.host == "api.odcloud.kr":
            calls["api"] += 1
            return httpx.Response(401, json={"code": -4, "msg": "do-not-expose-this-key"})
        calls["popup"] += 1
        return httpx.Response(200, text=fixture())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await competition.run_once(today=date(2026, 10, 1), client=client)
    assert calls == {"api": 1, "popup": 2}
    assert result["count"] == 2 and result["complete"] == 2 and result["fallback"] == 2
    with factory() as session:
        notices = session.scalars(select(Notice)).all()
        assert all(item.competition_state.status == "ok" and item.competition_state.complete for item in notices)
        status = session.get(SourceStatus, competition.SOURCE)
        assert "인증키 확인" in status.message and "do-not-expose" not in status.message
        assert all("do-not-expose" not in item.competition_state.message for item in notices)


@pytest.mark.asyncio
async def test_future_first_priority_defers_without_network(factory, monkeypatch):
    monkeypatch.setattr(competition, "SessionLocal", factory)
    monkeypatch.setattr(competition, "init_db", lambda: None)
    with factory() as session:
        upcoming = payload(first="2026-10-02")
        upcoming["events"][1]["start_date"] = "2026-10-03"
        upsert_notice(session, upcoming)
        session.commit()
    def handler(request):
        raise AssertionError("unpublished future results need no request")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await competition.run_once(today=date(2026, 10, 1), client=client)
    assert result["pending"] == 1 and result["count"] == 0
    with factory() as session:
        state = session.scalar(select(Notice)).competition_state
        assert state.status == "pending" and not state.complete


@pytest.mark.asyncio
async def test_api_figures_survive_popup_failure_without_closure_evidence(factory, monkeypatch):
    monkeypatch.setattr(competition, "SessionLocal", factory)
    monkeypatch.setattr(competition, "init_db", lambda: None)
    monkeypatch.setenv("CHEONGYAK_COMPETITION_API_KEY", "approved-test-key")
    with factory() as session:
        upsert_notice(session, payload())
        session.commit()
    def handler(request):
        if request.url.host == "api.odcloud.kr":
            return httpx.Response(200, json={"matchCount": 1, "data": [{
                "HOUSE_MANAGE_NO": "2026000399", "PBLANC_NO": "2026000399", "HOUSE_TY": "059.9442A",
                "MODEL_NO": "01", "SUPLY_HSHLDCO": 7, "SUBSCRPT_RANK_CODE": 1,
                "RESIDE_SECD": "01", "RESIDE_SENM": "해당지역", "REQ_CNT": "481", "CMPET_RATE": "68.71",
            }]})
        return httpx.Response(503, text="upstream failed")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await competition.run_once(today=date(2026, 10, 1), client=client)
    assert result["count"] == 1 and result["failed"] == 1
    with factory() as session:
        notice = session.scalar(select(Notice))
        assert notice.competition_state.status == "partial" and not notice.competition_state.complete
        assert "마감 결과 확인 실패" in notice.competition_state.message
        assert notice.competitions[0].competition_rate == "68.71"
        assert notice.competitions[0].result_status == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize('score_response', ['unpublished', 'error', 'additional', 'conflict'])
async def test_official_popup_scores_survive_empty_failed_or_partial_score_api(factory, monkeypatch, score_response):
    monkeypatch.setattr(competition, "SessionLocal", factory)
    monkeypatch.setattr(competition, "init_db", lambda: None)
    monkeypatch.setenv("CHEONGYAK_COMPETITION_API_KEY", "approved-test-key")
    html=(FIXTURES / "winning-score-public.html").read_text()
    raw=payload("2026000300")
    raw["prices"]=[{"unit_type":"084.9800A","price_kind":"sale_max","amount_krw":400_000_000,"verification":"official"}]
    with factory() as session:
        upsert_notice(session, raw)
        session.commit()
    paths=[]
    def handler(request):
        paths.append(request.url.path)
        if "getAptLttotPblancScore" in request.url.path:
            if score_response == 'error':
                return httpx.Response(401, json={"message":"approved-test-key"})
            if score_response in {'additional','conflict'}:
                return httpx.Response(200,json={'matchCount':1,'data':[{
                    'HOUSE_MANAGE_NO':'2026000300','PBLANC_NO':'2026000300',
                    'HOUSE_TY':'084.9800A','RESIDE_SECD':'02' if score_response == 'additional' else '01',
                    'LWET_SCORE':40,'TOP_SCORE':60,'AVRG_SCORE':45,
                }]})
        if request.url.host == "api.odcloud.kr":
            return httpx.Response(200, json={"matchCount":0,"data":[]})
        if score_response == 'error' and paths.count(request.url.path) > 1:
            return httpx.Response(503)
        return httpx.Response(200,text=html)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await competition.run_once(today=date(2026, 10, 1), client=client)
    with factory() as session:
        public=notice_public(related_notices(session, session.scalar(select(Notice))))
        assert any(row["min_score"] == 37 and row["residence_area"] == "local" for row in public.winning_scores)
        assert all(row["collection_status"] == "success" for row in public.winning_scores)
        assert all(row["criterion_date"] == "2026-09-28" for row in public.winning_scores)
        assert len(public.winning_scores) == (2 if score_response in {'additional','conflict'} else 1)
        assert 'approved-test-key' not in str(public.winning_scores)
    assert any("getAptLttotPblancScore" in path for path in paths)


@pytest.mark.asyncio
async def test_auth_and_public_screen_failure_disable_existing_exclusion(factory, monkeypatch):
    monkeypatch.setattr(competition, "SessionLocal", factory)
    monkeypatch.setattr(competition, "init_db", lambda: None)
    monkeypatch.setenv("CHEONGYAK_COMPETITION_API_KEY", "never-log-this-key")
    with factory() as session:
        notice = upsert_notice(session, payload())
        parsed = competition.parse_popup(fixture(), popup(), expected_unit_types=LOCAL_UNITS, observed_at=NOW)
        record_competition_result(session, notice, "ok", rows=parsed.rows, unit_types=parsed.unit_types, complete=True, observed_at=NOW)
        session.commit()
    def handler(request):
        return httpx.Response(401, json={"msg": "never-log-this-key"}) if request.url.host == "api.odcloud.kr" else httpx.Response(503)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await competition.run_once(today=date(2026, 10, 1), client=client)
    assert result["status"] == "error" and result["failed"] == 1
    with factory() as session:
        notice = session.scalar(select(Notice))
        assert notice.competition_state.status == "error" and not notice.competition_state.complete
        assert len(notice.competitions) == 16 and notice.competition_state.last_success_at.replace(tzinfo=timezone.utc) == NOW
        assert "never-log" not in notice.competition_state.message


@pytest.mark.asyncio
async def test_inflight_competition_fetch_cannot_certify_a_corrected_notice(factory, monkeypatch):
    monkeypatch.setattr(competition, "SessionLocal", factory)
    monkeypatch.setattr(competition, "init_db", lambda: None)
    monkeypatch.delenv("CHEONGYAK_COMPETITION_API_KEY", raising=False)
    monkeypatch.delenv("DATA_GO_KR_API_KEY", raising=False)
    raw = payload()
    with factory() as session:
        notice = upsert_notice(session, raw)
        parsed = competition.parse_popup(fixture(), popup(), expected_unit_types=LOCAL_UNITS, observed_at=NOW)
        record_competition_result(session, notice, "ok", rows=parsed.rows, unit_types=parsed.unit_types,
                                  complete=True, observed_at=NOW)
        notice_id = notice.id
        session.commit()

    def handler(request):
        # Commit a source correction while the worker's public fetch is in
        # flight. The long-lived collector still has version 1 cached.
        with factory() as session:
            upsert_notice(session, {"source": raw["source"], "external_id": raw["external_id"],
                                    "title": "정정된 모집공고"})
            session.commit()
        return httpx.Response(200, text=fixture().replace("68.71", "99.99"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await competition.run_once(today=date(2026, 10, 1), client=client)
    assert result["count"] == 0 and result["complete"] == 0 and result["pending"] == 1
    with factory() as session:
        notice = session.get(Notice, notice_id)
        assert notice.version == 2 and notice.title == "정정된 모집공고"
        assert notice.competition_state.status == "pending" and not notice.competition_state.complete
        assert "공고 변경" in notice.competition_state.message
        assert len(notice.competitions) == 16
        assert notice.competitions[0].competition_rate == "68.71"
        assert session.scalar(select(func.count()).select_from(CompetitionRevision)) == 1
        # A new fetch explicitly tied to the updated version may replace the
        # pending snapshot, so correction retry is not permanently blocked.
        fresh = competition.parse_popup(fixture().replace("68.71", "99.99"), popup(),
                                         expected_unit_types=LOCAL_UNITS, observed_at=NOW + timedelta(hours=3))
        state = record_competition_result(session, notice, "ok", rows=fresh.rows, unit_types=fresh.unit_types,
            complete=True, observed_at=NOW + timedelta(hours=3), expected_notice_version=notice.version)
        session.commit()
        assert state.status == "ok" and state.complete
        assert notice.competitions[0].competition_rate == "99.99"


def test_failure_preserves_history_and_reopen_replaces_closed_results(factory):
    with factory() as session:
        notice = upsert_notice(session, payload())
        result = competition.parse_popup(fixture(), popup(), expected_unit_types=LOCAL_UNITS, observed_at=NOW)
        record_competition_result(session, notice, "ok", rows=result.rows, unit_types=result.unit_types, complete=True, observed_at=NOW)
        session.commit()
        # Repeated identical polls update observed_at, not result history.
        record_competition_result(session, notice, "ok", rows=result.rows, unit_types=result.unit_types, complete=True, observed_at=NOW + timedelta(hours=1))
        session.commit()
        assert session.scalar(select(func.count()).select_from(CompetitionRevision)) == 1
        record_competition_result(session, notice, "error", message="공개 화면 HTTP 503", observed_at=NOW + timedelta(hours=2))
        session.commit()
        assert not notice.competition_state.complete and notice.competition_state.status == "error"
        assert len(notice.competitions) == 16
        assert notice.competition_state.last_success_at.replace(tzinfo=timezone.utc) == NOW + timedelta(hours=1)
        reopened = competition.parse_popup(fixture().replace("1순위 해당지역 마감(청약 접수 종료)", "청약 접수중"), popup(), expected_unit_types=LOCAL_UNITS)
        record_competition_result(session, notice, "ok", rows=reopened.rows, unit_types=reopened.unit_types, complete=True, observed_at=NOW + timedelta(hours=3))
        session.commit()
        assert notice.competition_state.complete
        assert all(row.result_status == "open" for row in notice.competitions)
        assert session.scalar(select(func.count()).select_from(CompetitionRevision)) == 2


def test_list_detail_source_merge_adds_competition_without_hiding_prices(factory):
    with factory() as session:
        primary = upsert_notice(session, payload(source="myhome"))
        secondary = upsert_notice(session, payload())
        parsed = competition.parse_popup(fixture(), popup(), expected_unit_types=LOCAL_UNITS, observed_at=NOW)
        record_competition_result(session, secondary, "ok", rows=parsed.rows, unit_types=parsed.unit_types, complete=True, evidence_url=popup(), observed_at=NOW)
        session.commit()
        assert secondary.duplicate_of_id == primary.id
        def dependency():
            yield session
        app.dependency_overrides[get_session] = dependency
        try:
            client = TestClient(app)
            listing = client.get("/api/notices", params={"start": "2026-10-01", "end": "2026-10-10", "application_only": "true"}).json()
            detail = client.get(f"/api/notices/{primary.id}").json()
            assert listing["total"] == 1
            item = listing["items"][0]
            assert len(item["prices"]) == 4 and len(item["competitions"]) == 16
            assert item["competition"]["complete"] and item["competition"]["unit_types"] == LOCAL_UNITS
            assert item["competition"] == detail["competition"]
            assert item["competitions"][0]["observed_at"].endswith("Z")
        finally:
            app.dependency_overrides.clear()
        changed = payload()
        changed["events"][1]["end_date"] = "2026-10-02"
        upsert_notice(session, changed)
        session.commit()
        assert secondary.competition_state.status == "pending" and not secondary.competition_state.complete


def test_results_filter_before_pagination_and_keep_ended_stale_failed_figures(factory):
    with factory() as session:
        notices = {}
        cases = [
            ("2026001001", "오래된 결과", "2026-09-29", "2026-10-01", "apt", "official"),
            ("2026001002", "최근 결과", "2026-10-01", "2026-10-02", "apt", "official"),
            ("2026001003", "진행 중 결과", "2026-10-02", "2026-10-10", "apt", "official"),
            ("2026001004", "공공임대 결과", "2026-10-02", "2026-10-03", "public_rental", "official"),
            ("2026001005", "미검증 결과", "2026-10-02", "2026-10-03", "apt", "ai_unverified"),
            ("2026001006", "미발표 공고", "2026-10-02", "2026-10-03", "apt", None),
            ("2026001007", "조회 기간 밖 결과", "2026-08-01", "2026-08-02", "apt", "official"),
        ]
        for no, title, start, end, category, verification in cases:
            raw = payload(no)
            raw.update(title=title, category=category, events=[
                {"kind": "general", "label": "접수", "start_date": start, "end_date": end},
                {"kind": "winner", "label": "당첨자 발표", "start_date": "2026-11-20"},
            ])
            notice = upsert_notice(session, raw)
            notices[no] = notice
            if verification:
                parsed = competition.parse_popup(fixture(), popup(no), expected_unit_types=LOCAL_UNITS, observed_at=NOW - timedelta(days=30))
                for row in parsed.rows:
                    row["verification"] = verification
                record_competition_result(session, notice, "ok", rows=parsed.rows, unit_types=parsed.unit_types,
                                          complete=True, observed_at=NOW - timedelta(days=30))
        record_competition_result(session, notices["2026001001"], "error", message="재확인 실패", observed_at=NOW)
        record_competition_result(session, notices["2026001002"], "pending", message="정정 후 재확인 대기", observed_at=NOW)
        session.commit()
        def dependency():
            yield session
        app.dependency_overrides[get_session] = dependency
        try:
            client = TestClient(app)
            params = {"view": "results", "start": "2026-09-25", "end": "2026-10-03",
                      "exclude_public_rental": "true", "page_size": 1}
            pages = [client.get("/api/notices", params={**params, "page": page}).json() for page in (1, 2, 3, 4)]
            assert [page["total"] for page in pages] == [3, 3, 3, 3]
            assert [page["items"][0]["title"] for page in pages[:3]] == ["진행 중 결과", "최근 결과", "오래된 결과"]
            assert [page["items"][0]["application_end_date"] for page in pages[:3]] == ["2026-10-10", "2026-10-02", "2026-10-01"]
            assert pages[3]["items"] == []
            archived = pages[2]["items"][0]
            assert archived["competition"]["status"] == "error"
            assert len(archived["competitions"]) == 16 and len(archived["prices"]) == 4
            assert archived["competitions"][0]["observed_at"] == "2026-09-01T01:00:00Z"
            assert client.get(f"/api/notices/{archived['id']}").json()["application_end_date"] == "2026-10-01"
            # Ending dates in winner/contract events do not extend reception.
            assert client.get("/api/notices", params={"view": "results", "start": "2026-11-20", "end": "2026-11-20"}).json()["total"] == 0
            assert client.get("/api/notices", params={**params, "exclude_public_rental": "false"}).json()["total"] == 4
            assert client.get("/api/notices", params={"view": "unknown"}).status_code == 422
        finally:
            app.dependency_overrides.clear()


def test_results_merge_saved_rows_despite_newer_pending_duplicate(factory):
    with factory() as session:
        primary = upsert_notice(session, payload(source="myhome"))
        secondary = upsert_notice(session, payload())
        parsed = competition.parse_popup(fixture(), popup(), expected_unit_types=LOCAL_UNITS, observed_at=NOW)
        record_competition_result(session, secondary, "ok", rows=parsed.rows, unit_types=parsed.unit_types, complete=True, observed_at=NOW)
        record_competition_result(session, primary, "pending", observed_at=NOW + timedelta(days=1))
        session.commit()
        def dependency():
            yield session
        app.dependency_overrides[get_session] = dependency
        try:
            listing = TestClient(app).get("/api/notices", params={"view": "results", "start": "2026-09-01", "end": "2026-10-01"}).json()
            assert listing["total"] == 1
            assert listing["items"][0]["id"] == primary.id
            assert len(listing["items"][0]["competitions"]) == 16
        finally:
            app.dependency_overrides.clear()


def test_results_correction_uses_new_snapshot_without_reusing_superseded_closure(factory):
    with factory() as session:
        original = upsert_notice(session, payload())
        parsed = competition.parse_popup(fixture(), popup(), expected_unit_types=LOCAL_UNITS, observed_at=NOW)
        record_competition_result(session, original, "ok", rows=parsed.rows, unit_types=parsed.unit_types, complete=True, observed_at=NOW)
        changed = payload("2026001000")
        changed.update(title="공식 경쟁률 검증 아파트 정정", correction_of_external_id=original.external_id,
                       events=[{"kind": "first_priority", "label": "정정 접수", "start_date": "2026-10-02", "audience": "해당지역"}])
        corrected = upsert_notice(session, changed)
        session.commit()
        def dependency():
            yield session
        app.dependency_overrides[get_session] = dependency
        try:
            client = TestClient(app)
            params = {"view": "results", "start": "2026-09-01", "end": "2026-10-03"}
            assert client.get("/api/notices", params=params).json()["total"] == 0
            reopened = competition.parse_popup(fixture().replace("1순위 해당지역 마감(청약 접수 종료)", "청약 접수중"),
                                               popup("2026001000"), expected_unit_types=LOCAL_UNITS, observed_at=NOW)
            record_competition_result(session, corrected, "ok", rows=reopened.rows, unit_types=reopened.unit_types, complete=True, observed_at=NOW)
            session.commit()
            listing = client.get("/api/notices", params=params).json()
            assert listing["total"] == 1 and listing["items"][0]["id"] == corrected.id
            assert listing["items"][0]["application_end_date"] == "2026-10-02"
            assert all(row["result_status"] == "open" for row in listing["items"][0]["competitions"])
            assert len(original.competitions) == 16  # Superseded raw data/history is retained.
            assert session.scalar(select(func.count()).select_from(CompetitionRevision)) == 2
        finally:
            app.dependency_overrides.clear()


def test_rule_enrichment_preserves_fresh_competition_but_known_document_change_requires_recheck(factory):
    with factory() as session:
        notice = upsert_notice(session, payload())
        parsed = competition.parse_popup(fixture(), popup(), expected_unit_types=LOCAL_UNITS, observed_at=NOW)
        record_competition_result(session, notice, "ok", rows=parsed.rows, unit_types=parsed.unit_types, complete=True, observed_at=NOW)
        session.commit()
        upsert_notice(session, {"source": notice.source, "external_id": notice.external_id, "document_hash": "first-doc",
                               "rules": [{"kind": "homeless", "value": True, "verification": "official",
                                          "document_hash": "first-doc", "evidence_text": "검토한 공고 조건"}]})
        session.commit()
        assert notice.competition_state.status == "ok" and notice.competition_state.complete
        assert len(notice.competitions) == 16 and notice.competition_state.last_success_at.replace(tzinfo=timezone.utc) == NOW
        upsert_notice(session, {"source": notice.source, "external_id": notice.external_id, "document_hash": "corrected-doc"})
        session.commit()
        assert notice.competition_state.status == "pending" and not notice.competition_state.complete
        assert len(notice.competitions) == 16  # Revalidation does not erase archived official figures.


@pytest.mark.asyncio
async def test_collects_ended_next_day_and_ninety_day_boundary_not_results_or_old_dates(factory, monkeypatch):
    monkeypatch.setattr(competition, "SessionLocal", factory)
    monkeypatch.setattr(competition, "init_db", lambda: None)
    monkeypatch.setenv("CHEONGYAK_COMPETITION_API_KEY", "")
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "")
    today = date(2026, 10, 3)
    with factory() as session:
        for no, when, kind in [
            ("2026001001", today - timedelta(days=1), "first_priority"),
            ("2026001002", today - timedelta(days=1), "general"),
            ("2026001003", today - timedelta(days=90), "first_priority"),
            ("2026001004", today - timedelta(days=91), "first_priority"),
            ("2026001005", today + timedelta(days=1), "first_priority"),
            ("2026001006", today, "winner"),
        ]:
            raw = payload(no)
            raw["events"] = [{"kind": kind, "label": "접수" if kind != "winner" else "당첨자 발표",
                              "start_date": when.isoformat(), "audience": "해당지역"}]
            upsert_notice(session, raw)
        session.commit()
    requested = []
    def handler(request):
        requested.append(request.url.params["pblancNo"])
        return httpx.Response(200, text=fixture())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await competition.run_once(today=today, client=client)
    assert set(requested) == {"2026001001", "2026001002", "2026001003"}
    assert result["count"] == 3 and result["pending"] == 1
    with factory() as session:
        by_no = {notice.external_id.split(":")[-1]: notice for notice in session.scalars(select(Notice))}
        assert len(by_no["2026001002"].competitions) == 16
        assert by_no["2026001004"].competition_state is None
        assert by_no["2026001005"].competition_state.status == "pending"
        assert by_no["2026001006"].competition_state is None


@pytest.mark.asyncio
async def test_ended_unpublished_results_are_retried_and_late_publication_is_saved(factory, monkeypatch):
    monkeypatch.setattr(competition, "SessionLocal", factory)
    monkeypatch.setattr(competition, "init_db", lambda: None)
    monkeypatch.setenv("CHEONGYAK_COMPETITION_API_KEY", "")
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "")
    with factory() as session:
        raw = payload(first="2026-10-01")
        raw["events"][1]["start_date"] = "2026-10-02"
        upsert_notice(session, raw)
        session.commit()
    published = False
    def handler(request):
        return httpx.Response(200, text=fixture() if published else '<table id="compitTbl"><tbody></tbody></table>')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await competition.run_once(today=date(2026, 10, 3), client=client)
        assert first["pending"] == 1 and first["rows"] == 0
        published = True
        second = await competition.run_once(today=date(2026, 10, 4), client=client)
    assert second["count"] == 1 and second["rows"] == 16
    with factory() as session:
        assert session.scalar(select(Notice)).competition_state.status == "ok"
        assert session.scalar(select(func.count()).select_from(CompetitionRevision)) == 1
