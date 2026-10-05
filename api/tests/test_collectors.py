"""Official source excerpts pin units, dates, and layout-sensitive parsing."""

from datetime import date
from datetime import datetime, timezone, timedelta

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from app.db import init_db, make_engine
from app.ingest.boards import link_board_corrections, normalize_gh_apply, table_rows
from app.ingest.myhome import parse_sale_detail
from app.ingest.reb import PAIRS, normalize as normalize_reb
from app.ingest import worker
from app.ingest import ih
from app.ingest.common import FeedError, get_json
from app.models import DocumentExtractionState, SourceStatus
from app.repository import record_source_status


def test_myhome_sale_detail_official_2026_09_28_excerpt():
    # Public detail: https://m.myhome.go.kr/hws/portal/sch/selectLttotHouseDetailView.do?pblancId=1485
    # Checked 2026-09-29. The detail explicitly labels sumPrice in 원 and
    # notes 1층 기본형; it must never be called 청약홈's highest sale amount.
    page = """
      <h5>공급 정보</h5>
      <script>
      houseList.push({houseSn : "1", hsmpNm : "원주무실 A-2",
        partclrMatter : "금액정보는 '1층 기본형' 기준 입니다."});
      suplyList.push({houseSn : "1", styleNm : "74A", prvuseAr : "74.84",
        sumPrice : "356990000"});
      suplyList.push({houseSn : "1", styleNm : "84A", prvuseAr : "84.79",
        sumPrice : "404190000"});
      </script>
      <tr><th>접수 일정</th><td><div class="rank">
        <p class="text-gray">2026년 10월 12일 ~ 2026년 10월 14일</p>
      </div></td></tr>
    """
    url = "https://m.myhome.go.kr/hws/portal/sch/selectLttotHouseDetailView.do?pblancId=1485"
    parsed = parse_sale_detail(page, url)
    assert [(price["unit_type"], price["amount_krw"]) for price in parsed["prices"]] == [
        ("74A", 356_990_000), ("84A", 404_190_000),
    ]
    assert all(price["price_kind"] == "sale_total" and "1층 기본형 기준" in price["basis_label"] for price in parsed["prices"])
    assert all(price["evidence_url"] == url and price["verification"] == "official" for price in parsed["prices"])
    assert parsed["events"] == [{
        "kind": "general", "label": "신청 접수", "start_date": "2026-10-12",
        "end_date": "2026-10-14", "audience": None,
    }]


def test_reb_price_is_highest_sale_amount_in_manwon_not_myhome_total():
    detail = {
        "HOUSE_MANAGE_NO": "123", "PBLANC_NO": "456", "HOUSE_NM": "공식 공고",
        "RCRIT_PBLANC_DE": "20260928", "PARCPRC_ULS_AT": "Y",
        "GNRL_RNK1_CRSPAREA_RCPTDE": "20261007",
    }
    models = [
        {"HOUSE_TY": "059.9000A", "LTTOT_TOP_AMOUNT": "93500"},
        {"HOUSE_TY": "084.9000A", "LTTOT_TOP_AMOUNT": "124500"},
    ]
    result = normalize_reb(detail, models, PAIRS[0])
    assert result is not None
    assert result["price_cap_status"] == "yes"
    assert [price["amount_krw"] for price in result["prices"]] == [935_000_000, 1_245_000_000]
    assert all(price["price_kind"] == "sale_max" and price["basis_label"] == "주택형별 최고 분양금액" for price in result["prices"])


def test_reb_mixed_feed_uses_documented_house_subtype_codes():
    detail = {"HOUSE_MANAGE_NO": "1", "PBLANC_NO": "2", "HOUSE_NM": "생활형 숙박시설",
              "SEARCH_HOUSE_SECD": "0204"}
    result = normalize_reb(detail, [{"GP": "A", "TP": "59", "SUPLY_AMOUNT": "50000"}], PAIRS[1])
    assert result is not None
    assert result["category"] == "living_accommodation"
    assert result["prices"][0]["amount_krw"] == 500_000_000
    detail["SEARCH_HOUSE_SECD"] = "0203"
    rental = normalize_reb(detail, [{"GP": "A", "TP": "59", "SUPLY_AMOUNT": "50000"}], PAIRS[1])
    assert rental is not None
    assert rental["category"] == "private_rental"
    assert rental["prices"][0]["amount_krw"] is None
    assert rental["prices"][0]["price_kind"] == "deposit"


@pytest.mark.parametrize("code,kind", [("01", "private"), ("03", "national"), ("", "unknown"), ("02", "unknown")])
def test_reb_classification_uses_only_apt_official_subtype(code, kind):
    detail = {"HOUSE_MANAGE_NO": "1", "PBLANC_NO": "2", "HOUSE_NM": "LH 공고",
              "HOUSE_DTL_SECD": code, "HOUSE_SECD": "01", "BSNS_MBY_NM": "LH",
              "RCRIT_PBLANC_DE": "20260928"}
    apt = normalize_reb(detail, [], PAIRS[0])
    assert apt["rules"][0]["housing_kind"] == kind
    assert apt["rules"][0]["effect"] == "metadata"
    assert apt["rules"][0]["verification"] == ("official" if kind != "unknown" else "unknown")
    # On the urban endpoint code 03 denotes private rental. Its identical code
    # must not be promoted to 국민주택 by a generic code/name/provider heuristic.
    urban = normalize_reb(detail, [], PAIRS[1])
    assert urban["rules"][0]["housing_kind"] == ("not_applicable" if code == "02" else "unknown")


def test_reb_context_preserves_unknown_and_distinguishes_public_housing_district():
    detail = {"HOUSE_MANAGE_NO": "1", "PBLANC_NO": "2", "HOUSE_NM": "국민주택",
              "HOUSE_DTL_SECD": "03", "SUBSCRPT_AREA_CODE_NM": "경기",
              "SPECLT_RDN_EARTH_AT": "N", "MDAT_TRGET_AREA_SECD": "Y",
              "PUBLIC_HOUSE_EARTH_AT": "Y", "PUBLIC_HOUSE_SPCLW_APPLC_AT": "Y"}
    context = normalize_reb(detail, [], PAIRS[0])["rules"][1]["value"]
    assert context["capital_region"] is True
    assert context["speculation_zone"] is False
    assert context["subscription_overheated"] is True
    assert context["weakened_area"] is None
    assert context["public_housing"] is None
    assert context["public_housing_district"] is True
    assert context["public_housing_special_law"] is True
    assert context["rule_effective_date"] is None
    assert normalize_reb({"HOUSE_MANAGE_NO": "1", "PBLANC_NO": "2", "HOUSE_NM": "자료 미공개"}, [], PAIRS[0])["rules"][1]["value"]["capital_region"] is None


def test_gh_apply_board_handles_missing_closing_cells_and_links_official_detail():
    # The current GH rental board omits several </td> tags between columns.
    page = """
      <table><tbody><tr>
      <td>1</td><td>행복주택</td>
      <td><a href="#a" data-pbancNo="811">연천BIX 경기행복주택 추가모집 공고</a></td>
      <td>연천군<td>첨부</td><td>2026-08-24</td><td>-</td>
      </tr></tbody></table>
    """
    rows = table_rows(page)
    result = normalize_gh_apply(rows[0], "/sb/sr/sr7150/selectPbancRentHouseList.do")
    assert result is not None
    assert result["announcement_date"] == "2026-08-24"
    assert result["region_name"] == "경기도 연천군"
    assert result["official_url"] == "https://apply.gh.or.kr/sb/sr/sr7150/selectPbancDetailView.do?pbancNo=811"
    assert result["events"] == []


def test_sh_labeled_correction_links_exact_prior_title():
    # SH public-sale board carried these original/correction sequence numbers.
    rows = [
        {"external_id": "301479", "title": "[정정] 마곡지구 17단지 토지임대부 분양주택 입주자모집공고",
         "category": "public_sale", "announcement_date": "2026-03-10"},
        {"external_id": "301076", "title": "마곡지구 17단지 토지임대부 분양주택 입주자모집공고",
         "category": "public_sale", "announcement_date": "2026-02-27"},
    ]
    link_board_corrections(rows)
    assert rows[0]["correction_of_external_id"] == "301076"


@pytest.mark.asyncio
async def test_ih_uses_documented_page_limit_and_iso_date_range():
    # Official Swagger: https://www.data.go.kr/data/15149725/openapi.do
    # numOfRows must be 1–30 (421 otherwise); date filters require yyyy-MM-dd.
    requested_pages = []
    def page_response(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(ih.URL)
        params = request.url.params
        assert params["serviceKey"] == "test-key"
        assert params["numOfRows"] == "30"
        assert params["startCrtrYmd"] == "2026-09-01"
        assert params["endCrtrYmd"] == "2026-10-31"
        page = int(params["pageNo"])
        requested_pages.append(page)
        numbers = range(1, 31) if page == 1 else range(31, 32)
        return httpx.Response(200, json={"header": {"resultCode": "200"}, "body": {
            "totalCount": 31,
            "posts": [{"sj": f"분양 공고 {number}", "link": f"https://ih.example/notice/{number}",
                       "seNm": "분양", "crtYmd": "2026-09-30"} for number in numbers],
        }})

    async with httpx.AsyncClient(transport=httpx.MockTransport(page_response)) as client:
        notices = await ih.collect(client, "test-key", date(2026, 9, 1), date(2026, 10, 31))
    assert requested_pages == [1, 2]
    assert len(notices) == 31
    assert all(notice["category"] == "public_sale" for notice in notices)


@pytest.mark.asyncio
@pytest.mark.parametrize("code,cause", [
    ("30", "등록되지 않은 API 키"),
    ("20", "API 접근 권한"),
    ("31", "API 키 유효기간"),
])
async def test_http_403_gateway_error_is_actionable_without_echoing_secrets(code, cause):
    secret = "sensitive-service-key-123"
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["serviceKey"] == secret
        return httpx.Response(403, json={"OpenAPI_ServiceResponse": {"cmmMsgHeader": {
            "returnReasonCode": code,
            "returnAuthMsg": f"SERVICE_KEY_IS_NOT_REGISTERED_ERROR {secret}",
            "errMsg": f"{request.url}",
        }}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FeedError) as raised:
            await get_json(client, "https://official.example/api", {"serviceKey": secret}, attempts=1)
    assert raised.value.status_code == 403
    assert raised.value.result_code == code
    assert cause in str(raised.value)
    assert secret not in str(raised.value)
    assert "official.example" not in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    [{"CMN": {"SS_CODE": "N", "MESSAGE": "secret-api-key"}}],
    {"response": {"header": {"resultCode": "secret-api-key", "resultMsg": "secret-api-key"}}},
])
async def test_unknown_upstream_result_code_fails_closed_without_echo(body):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=body)
    )) as client:
        with pytest.raises(FeedError) as raised:
            await get_json(client, "https://official.example/api", {"serviceKey": "secret-api-key"}, attempts=1)
    assert "상위 API 오류 응답" in str(raised.value)
    assert "secret-api-key" not in str(raised.value)


@pytest.mark.asyncio
async def test_running_status_is_committed_before_request_and_error_retains_success(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'running.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "init_db", lambda: None)
    monkeypatch.setattr(worker, "extraction_configured", lambda: False)
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "private-api-key")
    old_success = datetime(2026, 9, 28, 9, tzinfo=timezone.utc)
    with factory() as session:
        record_source_status(session, "cheongyak_home", "ok", "이전 성공", old_success, 17)
        session.commit()

    observed_running = False
    async def reb_collect(client, key, start, end):
        nonlocal observed_running
        with factory() as session:
            status = session.get(SourceStatus, "cheongyak_home")
            assert status is not None
            assert status.status == "running"
            assert status.last_success_at is not None
            assert status.record_count == 17
            observed_running = True
        await get_json(client, "https://official.example/api", {"serviceKey": key}, attempts=1)

    async def empty_collect(*args):
        return []

    async def empty_gh(*args):
        return [], None

    monkeypatch.setattr(worker.reb, "collect", reb_collect)
    for source in (worker.myhome, worker.lh, worker.ih):
        monkeypatch.setattr(source, "collect", empty_collect)
    monkeypatch.setattr(worker.boards, "collect_sh", empty_collect)
    monkeypatch.setattr(worker.boards, "collect_gh", empty_gh)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"OpenAPI_ServiceResponse": {"cmmMsgHeader": {
            "returnReasonCode": "30", "errMsg": str(request.url),
        }}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await worker.run_once(today=date(2026, 9, 30), client=client)
    assert observed_running
    assert result["cheongyak_home"]["status"] == "error"
    with factory() as session:
        status = session.get(SourceStatus, "cheongyak_home")
        assert status is not None
        assert status.status == "error"
        assert "등록되지 않은 API 키" in status.message
        assert "private-api-key" not in status.message
        assert "official.example" not in status.message
        assert status.last_success_at is not None
        assert status.record_count == 17
    engine.dispose()


@pytest.mark.asyncio
async def test_free_tier_deferral_survives_worker_restart(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'cooldown.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "extraction_configured", lambda: True)
    calls = 0

    async def defer(payload, **kwargs):
        nonlocal calls
        calls += 1
        return {**payload, "extraction_status": "deferred"}

    monkeypatch.setattr(worker, "enrich_notice", defer)
    payload = {
        "source": "myhome", "external_id": "sale-1", "title": "공공분양 모집공고",
        "category": "public_sale", "announcement_date": "2026-09-29",
        "official_url": "https://www.myhome.go.kr/notice/1",
        "events": [{"kind": "general", "label": "접수", "start_date": "2026-10-02"}],
    }
    async with httpx.AsyncClient() as client:
        first = await worker._save_rows("myhome", [payload.copy()], client, date(2026, 9, 29))
        second = await worker._save_rows("myhome", [payload.copy()], client, date(2026, 9, 29))
    assert calls == 1
    assert first[-1] == "partial" and second[-1] == "partial"
    with factory() as session:
        state = session.get(DocumentExtractionState, ("myhome", "sale-1"))
        assert state is not None and state.deferred_until is not None
        assert state.audited_on == date(2026, 9, 29)  # Local work completed independently.
        # Expire only the temporary AI cooldown; a same-day cycle must retry
        # that model work even though today's local audit already happened.
        state.deferred_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
        status = session.get(SourceStatus, "myhome")
        assert status is not None and status.last_success_at is not None
        assert "주택형 가격 미확인" in status.message
    async with httpx.AsyncClient() as client:
        await worker._save_rows("myhome", [payload.copy()], client, date(2026, 9, 29))
    assert calls == 2
    engine.dispose()


@pytest.mark.asyncio
async def test_free_quota_pauses_all_documents_across_worker_cycles(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'global-quota.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "extraction_configured", lambda: True)
    calls = 0
    local_calls = 0

    async def quota(payload, **kwargs):
        nonlocal calls, local_calls
        local_calls += 1
        if kwargs.get("allow_gemini"):
            calls += 1
            return {**payload, "extraction_status": "quota"}
        return payload

    monkeypatch.setattr(worker, "enrich_notice", quota)
    rows = [
        {
            "source": "myhome", "external_id": f"sale-{number}", "title": f"공공분양 {number}",
            "category": "public_sale", "announcement_date": "2026-09-29",
            "official_url": f"https://www.myhome.go.kr/notice/{number}",
            "events": [{"kind": "general", "label": "접수", "start_date": "2026-10-02"}],
        }
        for number in (1, 2)
    ]
    async with httpx.AsyncClient() as client:
        first = await worker._save_rows("myhome", [row.copy() for row in rows], client, date(2026, 9, 29))
        second = await worker._save_rows("myhome", [row.copy() for row in rows], client, date(2026, 9, 29))
    assert calls == 1
    assert local_calls == 2  # Second document still receives local processing.
    assert first[2] == 2 and second[2] == 2
    with factory() as session:
        state = session.get(DocumentExtractionState, worker.QUOTA_STATE_KEY)
        assert state is not None and state.deferred_until is not None
    engine.dispose()
