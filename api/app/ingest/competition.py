"""Official competition figures and explicit APT result-table evidence.

The API does not publish an APT closure result. Only the public #compitTbl
result cells establish that first priority closed in the local area. Numeric
rates and applicant totals never establish closure. Run this module directly
to collect figures without repeating notices or document extraction.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote, urlencode
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select

from app.db import SessionLocal, init_db
from app.models import Notice, NoticeEvent
from app.repository import NON_APPLICATION_KINDS, is_open_ended_application, record_competition_result, record_source_status

from .common import FeedError, get_json, integer, value

SOURCE = "cheongyak_competition"
API_BASE = "https://api.odcloud.kr/api/ApplyhomeInfoCmpetRtSvc/v1"
POPUP_URL = "https://www.applyhome.co.kr/ai/aia/selectAPTCompetitionPopup.do"
KST = ZoneInfo("Asia/Seoul")
LOGGER = logging.getLogger("cheongyak.competition")
OPERATIONS = {
    "getAPTLttotPblancDetail": "getAPTLttotPblancCmpet",
    "getUrbtyOfctlLttotPblancDetail": "getUrbtyOfctlLttotPblancCmpet",
    "getRemndrLttotPblancDetail": "getRemndrLttotPblancCmpet",
    "getPblPvtRentLttotPblancDetail": "getPblPvtRentLttotPblancCmpet",
    "getOPTLttotPblancDetail": "getOPTLttotPblancCmpet",
}
AREA_BY_LABEL = {"해당지역": "local", "기타지역": "other", "기타경기": "other_gyeonggi"}
AREA_BY_CODE = {"01": "local", "02": "other", "03": "other_gyeonggi"}
LOCAL_CLOSED_TEXT = "1순위해당지역마감(청약접수종료)"
RESULT_LOOKBACK_DAYS = 90


def unit_key(raw: Any) -> str:
    return re.sub(r"[.\s]", "", str(raw or "")).upper()


def _compact(raw: str) -> str:
    return re.sub(r"\s+", "", raw)


def result_status(text: str) -> str:
    compact = _compact(text)
    if compact == LOCAL_CLOSED_TEXT:
        return "local_first_closed"
    if compact == "1순위마감(청약접수종료)":
        return "first_closed"
    if compact == "청약접수중":
        return "open"
    return "unknown"


class CompetitionTableParser(HTMLParser):
    """Read result cells only inside tbody of the official result table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.table_depth = 0
        self.in_tbody = False
        self.found_table = False
        self.closed_table = False
        self.row: dict | None = None
        self.cell: dict | None = None
        self.rows: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "table":
            if self.table_depth:
                self.table_depth += 1
            elif attr.get("id") == "compitTbl" and not self.found_table:
                self.table_depth = 1
                self.found_table = True
            return
        if self.table_depth != 1:
            return
        if tag == "tbody":
            self.in_tbody = True
        elif self.in_tbody and tag == "tr":
            self.row = {"attrs": attr, "cells": []}
        elif self.row is not None and tag == "td":
            self._close_cell()
            self.cell = {"class": attr.get("class", ""), "parts": []}

    def handle_data(self, data: str) -> None:
        if self.table_depth == 1 and self.cell is not None:
            self.cell["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self.table_depth:
            self.table_depth -= 1
            if not self.table_depth:
                self.closed_table = True
                self.in_tbody = False
            return
        if self.table_depth != 1:
            return
        if tag == "td":
            self._close_cell()
        elif tag == "tr" and self.row is not None:
            self._close_cell()
            self.rows.append(self.row)
            self.row = None
        elif tag == "tbody":
            self.in_tbody = False

    def _close_cell(self) -> None:
        if self.cell is not None and self.row is not None:
            self.cell["text"] = " ".join("".join(self.cell["parts"]).split())
            self.row["cells"].append(self.cell)
            self.cell = None


@dataclass
class CompetitionResult:
    rows: list[dict] = field(default_factory=list)
    unit_types: list[str] = field(default_factory=list)
    complete: bool = False
    winning_scores: list[dict] = field(default_factory=list, kw_only=True)
    evidence_url: str | None = None
    message: str | None = None
    status: str = "ok"


def parse_popup(
    html: str, evidence_url: str, *, expected_unit_types: list[str] | None = None,
    observed_at: datetime | None = None,
) -> CompetitionResult:
    parser = CompetitionTableParser()
    parser.feed(html)
    if not parser.found_table or not parser.closed_table:
        raise FeedError("청약홈 공식 경쟁률 표를 확인하지 못했습니다. 공개 화면 구조를 확인하세요.")
    rows: list[dict] = []
    units: list[str] = []
    observed_at = observed_at or datetime.now(timezone.utc)
    for raw in parser.rows:
        attrs, cells = raw["attrs"], raw["cells"]
        # Totals, headers, explanatory templates, and hidden off-table sample
        # text cannot create results. Each real row has these source attributes.
        if not attrs.get("data-ty"):
            continue
        if len(cells) < 7 or "cpHouseTy" not in cells[0]["class"].split() or "cpSubscrptRt" not in cells[6]["class"].split():
            raise FeedError("청약홈 경쟁률 표의 열 구조가 변경되었습니다. 마감 판독을 중단합니다.")
        unit = cells[0]["text"]
        if not unit or unit_key(unit) != unit_key(attrs["data-ty"]):
            raise FeedError("청약홈 경쟁률 주택형 식별이 일치하지 않습니다.")
        label = cells[3]["text"]
        if _compact(label) != _compact(attrs.get("data-sem") or ""):
            raise FeedError("청약홈 경쟁률 거주지역 식별이 일치하지 않습니다.")
        rank_class = cells[2]["class"].split()
        rank = 1 if "cpRank1" in rank_class else 2 if "cpRank2" in rank_class else None
        if rank is None or _compact(cells[2]["text"]) != f"{rank}순위":
            raise FeedError("청약홈 경쟁률 순위를 확인하지 못했습니다.")
        area = AREA_BY_LABEL.get(_compact(label), "unknown")
        result = cells[6]["text"]
        rows.append({
            "source": SOURCE, "unit_type": unit, "model_no": None,
            "rank": rank, "residence_area": area, "residence_area_label": label,
            "supply_type": "general", "supply_type_label": "일반공급", "resident_priority": None,
            "supply_count": integer(cells[1]["text"]), "application_count": integer(cells[4]["text"]),
            "competition_rate": cells[5]["text"] or "-", "result_status": result_status(result),
            "result_text": result or None, "evidence_url": evidence_url,
            "verification": "official", "observed_at": observed_at,
        })
        if unit not in units:
            units.append(unit)
    actual = {unit_key(unit) for unit in units}
    expected = {unit_key(unit) for unit in expected_unit_types or [] if unit_key(unit)}
    full_first_rows = all(
        any(unit_key(row["unit_type"]) == unit_key(unit) and row["rank"] == 1 and row["residence_area"] == "local" for row in rows)
        and any(unit_key(row["unit_type"]) == unit_key(unit) and row["rank"] == 1 and row["residence_area"] in {"other", "other_gyeonggi"} for row in rows)
        for unit in units
    )
    # A complete official model inventory is needed as an independent check
    # against partial pages. Missing prices themselves do not remove a model.
    complete = bool(rows and expected and actual == expected and full_first_rows)
    from .winning_scores import parse_score_popup
    from urllib.parse import parse_qs, urlparse
    params = parse_qs(urlparse(evidence_url).query)
    scores = parse_score_popup(html, url=evidence_url, house_no=(params.get('houseManageNo') or [''])[0], notice_no=(params.get('pblancNo') or [''])[0], observed_at=observed_at.isoformat())
    return CompetitionResult(rows, units, complete, evidence_url, winning_scores=scores)


def normalize_api_row(raw: dict, operation: str, evidence_url: str, observed_at: datetime) -> dict | None:
    unit = str(value(raw, "HOUSE_TY") or "").strip()
    if not unit:
        return None
    rank = integer(raw.get("SUBSCRPT_RANK_CODE"))
    rank = rank if rank in {1, 2} else None
    label = str(value(raw, "RESIDE_SENM", "RESIDNT_PRIOR_SENM") or "").strip() or None
    area = AREA_BY_CODE.get(str(raw.get("RESIDE_SECD") or "").zfill(2), "unknown")
    supply_code = str(raw.get("SPSPLY_KND_CODE") or "")
    supply_type = ({"00": "general", "SY": "young", "SN": "newlywed", "SO": "older"}.get(supply_code, "unknown")
                   if operation == "getPblPvtRentLttotPblancCmpet" else "general")
    return {
        "source": SOURCE, "unit_type": unit, "model_no": str(raw["MODEL_NO"]) if raw.get("MODEL_NO") is not None else None,
        "rank": rank, "residence_area": area, "residence_area_label": label,
        "supply_type": supply_type, "supply_type_label": value(raw, "SPSPLY_KND_NM") or ("일반공급" if supply_type == "general" else None),
        "resident_priority": str(raw["RESIDNT_PRIOR_AT"]) if raw.get("RESIDNT_PRIOR_AT") is not None else None,
        "supply_count": integer(value(raw, "SPSPLY_KND_HSHLDCO", "SUPLY_HSHLDCO")),
        "application_count": integer(raw.get("REQ_CNT")), "competition_rate": str(raw["CMPET_RATE"]) if raw.get("CMPET_RATE") is not None else "-",
        # Swagger contains no first-priority result-status field.
        "result_status": "unknown", "result_text": None, "evidence_url": evidence_url,
        "verification": "official", "observed_at": observed_at,
    }


async def collect_api(client: httpx.AsyncClient, key: str, operation: str, house_no: str, notice_no: str, observed_at: datetime) -> list[dict]:
    url = f"{API_BASE}/{operation}"
    result: list[dict] = []
    for page in range(1, 21):
        body = await get_json(client, url, {
            "serviceKey": key, "cond[HOUSE_MANAGE_NO::EQ]": house_no, "cond[PBLANC_NO::EQ]": notice_no,
            "page": page, "perPage": 100, "returnType": "JSON",
        })
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise FeedError("청약홈 경쟁률 API 응답 형식 오류")
        batch = body["data"]
        for raw in batch:
            if not isinstance(raw, dict) or str(raw.get("HOUSE_MANAGE_NO")) != house_no or str(raw.get("PBLANC_NO")) != notice_no:
                raise FeedError("청약홈 경쟁률 API 공고 식별이 일치하지 않습니다.")
            normalized = normalize_api_row(raw, operation, url, observed_at)
            if normalized:
                result.append(normalized)
        matched = integer(body.get("matchCount"))
        if not batch or len(batch) < 100 or (matched is not None and page * 100 >= matched):
            return result
    raise FeedError("청약홈 경쟁률 API 페이지 상한 초과")


async def collect_popup(client: httpx.AsyncClient, house_no: str, notice_no: str, *, expected_unit_types: list[str], observed_at: datetime) -> CompetitionResult:
    params = {"houseManageNo": house_no, "pblancNo": notice_no}
    try:
        response = await client.get(POPUP_URL, params=params, timeout=25)
    except httpx.RequestError as exc:
        raise FeedError(f"청약홈 공개 경쟁률 연결 실패: {type(exc).__name__}") from None
    if response.status_code != 200:
        raise FeedError(f"청약홈 공개 경쟁률 HTTP {response.status_code}")
    evidence_url = f"{POPUP_URL}?{urlencode(params)}"
    return parse_popup(response.text, evidence_url, expected_unit_types=expected_unit_types, observed_at=observed_at)


def _identity(notice: Notice) -> tuple[str, str, str] | None:
    parts = notice.external_id.split(":")
    if len(parts) != 3 or parts[0] not in OPERATIONS or not all(re.fullmatch(r"\d+", part) for part in parts[1:]):
        return None
    return OPERATIONS[parts[0]], parts[1], parts[2]


def _is_published_window(notice: Notice, today: date, operation: str) -> bool:
    if notice.competitions:
        return True
    applications = [event for event in notice.events if event.kind not in NON_APPLICATION_KINDS]
    # Final figures often arrive after reception ends. Even an incomplete
    # imported APT schedule without a distinct local first-priority date must
    # be checked once all its known reception dates have elapsed.
    if applications and not any(is_open_ended_application(event) for event in applications) and max(event.end_date or event.start_date for event in applications) < today:
        return True
    if operation == "getAPTLttotPblancCmpet":
        local = [event for event in notice.events if event.kind == "first_priority" and event.audience == "해당지역"]
        return bool(local and min(event.start_date for event in local) <= today)
    return bool(applications and min(event.start_date for event in applications) <= today)


async def run_once(*, today: date | None = None, client: httpx.AsyncClient | None = None) -> dict:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    init_db()
    today = today or datetime.now(KST).date()
    key = unquote((os.getenv("CHEONGYAK_COMPETITION_API_KEY", "") or os.getenv("DATA_GO_KR_API_KEY", "")).strip())
    own_client = client is None
    client = client or httpx.AsyncClient(headers={"User-Agent": "CheongyakCalendar/1.0 (+public housing notice index)"}, follow_redirects=True)
    counts = {"count": 0, "rows": 0, "pending": 0, "failed": 0, "complete": 0, "fallback": 0}
    api_auth_failed = False
    try:
        with SessionLocal() as session:
            record_source_status(session, SOURCE, "running", "공식 경쟁률과 주택형별 마감 결과 수집 중")
            session.commit()
            matching_event = select(NoticeEvent.id).where(
                NoticeEvent.notice_id == Notice.id, NoticeEvent.kind.not_in(NON_APPLICATION_KINDS),
                func.coalesce(NoticeEvent.end_date, NoticeEvent.start_date) >= today - timedelta(days=RESULT_LOOKBACK_DAYS),
                NoticeEvent.start_date <= today + timedelta(days=90),
            ).exists()
            notices = session.scalars(select(Notice).where(Notice.source == "cheongyak_home", matching_event).order_by(Notice.announcement_date.desc(), Notice.id)).all()
            for notice in notices:
                identity = _identity(notice)
                if identity is None:
                    continue
                operation, house_no, notice_no = identity
                now = datetime.now(timezone.utc)
                if not _is_published_window(notice, today, operation):
                    record_competition_result(session, notice, "pending", message="접수 시작 전 · 공식 경쟁률 발표 대기", observed_at=now)
                    session.commit()
                    counts["pending"] += 1
                    continue
                record_competition_result(session, notice, "running", message="공식 경쟁률 확인 중", observed_at=now)
                session.commit()
                # The recorder refreshed the retained notice under its lock.
                # Use that current source identity, and reject a result if a
                # revision commits while the public network request runs.
                identity = _identity(notice)
                if identity is None:
                    record_competition_result(session, notice, "pending", message="공고 변경 후 경쟁률 재확인 대기", observed_at=now)
                    session.commit()
                    counts["pending"] += 1
                    continue
                operation, house_no, notice_no = identity
                fetched_version = notice.version
                api_rows: list[dict] = []
                api_error: FeedError | None = None
                if key and not api_auth_failed:
                    try:
                        api_rows = await collect_api(client, key, operation, house_no, notice_no, now)
                    except FeedError as exc:
                        api_error = exc
                        if exc.status_code in {401, 403} or exc.result_code in {20, 30, "20", "30"}:
                            api_auth_failed = True
                result = None
                try:
                    if operation == "getAPTLttotPblancCmpet":
                        try:
                            result = await collect_popup(client, house_no, notice_no,
                                expected_unit_types=[price.unit_type for price in notice.prices], observed_at=now)
                        except FeedError as exc:
                            if not api_rows:
                                raise
                            # API figures remain useful even if result-table
                            # evidence fails. Their result_status stays unknown.
                            result = CompetitionResult(api_rows, list(dict.fromkeys(row["unit_type"] for row in api_rows)),
                                False, api_rows[0]["evidence_url"],
                                f"공식 API 경쟁률 표시 · 마감 결과 확인 실패: {exc}", "partial")
                            counts["failed"] += 1
                        # API model identifiers supplement rows, but closure and
                        # result cells always come from the official popup.
                        model_ids = {(unit_key(row["unit_type"]), row["rank"], row["residence_area"]): row["model_no"] for row in api_rows}
                        for row in result.rows:
                            row["model_no"] = model_ids.get((unit_key(row["unit_type"]), row["rank"], row["residence_area"]))
                        if not api_rows:
                            counts["fallback"] += 1
                        if result.status == "ok" and (api_error or api_auth_failed):
                            result.message = "공식 공개 경쟁률 화면 사용 · 경쟁률 API 활용신청과 인증키 확인 필요"
                    elif api_error:
                        raise api_error
                    elif not key or api_auth_failed:
                        raise FeedError("경쟁률 API 인증키와 해당 서비스 활용신청을 확인하세요. 이 유형의 공개 화면 보완은 지원되지 않습니다.")
                    else:
                        result = CompetitionResult(api_rows, list(dict.fromkeys(row["unit_type"] for row in api_rows)), False,
                                                   f"{API_BASE}/{operation}")
                    if not result.rows:
                        record_competition_result(session, notice, "pending", evidence_url=result.evidence_url,
                            message="공식 경쟁률 미공개 · 다음 수집에서 다시 확인", observed_at=now,
                            expected_notice_version=fetched_version)
                        counts["pending"] += 1
                    else:
                        state = record_competition_result(session, notice, result.status, rows=result.rows, unit_types=result.unit_types,
                            complete=result.complete, evidence_url=result.evidence_url, message=result.message, observed_at=now,
                            expected_notice_version=fetched_version)
                        if state.status == "pending":
                            counts["pending"] += 1
                        else:
                            counts["count"] += 1
                            counts["rows"] += len(result.rows)
                            counts["complete"] += int(state.complete)
                except Exception as exc:
                    message = str(exc) if isinstance(exc, FeedError) else f"경쟁률 수집 실패: {type(exc).__name__}"
                    record_competition_result(session, notice, "error", message=message, observed_at=now,
                                              expected_notice_version=fetched_version)
                    counts["failed"] += 1
                    LOGGER.warning("Official competition collection failed: %s", type(exc).__name__)
                session.commit()
                if operation == "getAPTLttotPblancCmpet":
                    from .winning_scores import collect_winning_scores, record_winning_scores
                    table_failed = result is None or "selectAPTCompetitionPopup.do" not in result.evidence_url
                    status_score = "error" if table_failed else "success" if result.winning_scores else "unpublished"
                    rows_score = result.winning_scores if result else []
                    if key and not api_auth_failed:
                        try:
                            api_scores, api_score_status = await collect_winning_scores(client, key, house_no, notice_no)
                            if api_scores:
                                # Keep independently published popup rows when
                                # the API has only part of the score inventory.
                                # Conflicting official values remain separate
                                # so the browser can decline a comparison.
                                merged_scores = []
                                seen_scores = set()
                                for row in [*api_scores, *rows_score]:
                                    score_identity = (unit_key(row["unit_type"]), row["residence_area"],
                                        row["house_manage_no"], row["notice_no"], row["supply_type"], row["rank"],
                                        row["selection_path"], row["min_score"], row["max_score"], row["average_score"])
                                    if score_identity not in seen_scores:
                                        seen_scores.add(score_identity)
                                        merged_scores.append(row)
                                rows_score, status_score = merged_scores, api_score_status
                            elif not rows_score:
                                status_score = api_score_status
                        except Exception:
                            # Current official popup evidence remains useful
                            # even if the additional score API cannot respond.
                            if not rows_score:
                                status_score = "error"
                    record_winning_scores(session, notice.id, rows_score, status_score, expected_version=fetched_version, criterion_date=notice.announcement_date.isoformat() if notice.announcement_date else None)
                    session.commit()
            status = "error" if counts["failed"] and not counts["count"] else "partial" if counts["failed"] or counts["pending"] or counts["fallback"] or counts["complete"] < counts["count"] else "ok"
            message = f"공고 {counts['count']}건 · 경쟁률 {counts['rows']}행 · 전체 주택형 확인 {counts['complete']}건"
            if counts["pending"]:
                message += f" · 발표 대기 {counts['pending']}건"
            if counts["failed"]:
                message += f" · 확인 실패 {counts['failed']}건"
            if counts["fallback"]:
                message += f" · 공식 공개 화면 보완 {counts['fallback']}건"
            if api_auth_failed:
                message += " · 경쟁률 API 활용신청과 인증키 확인 필요"
            record_source_status(session, SOURCE, status, message, record_count=counts["count"])
            session.commit()
            return {"status": status, **counts}
    finally:
        if own_client:
            await client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect official competition figures without notice/document collection")
    parser.add_argument("--once", action="store_true", help="Run one competition collection cycle")
    parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    LOGGER.info("Competition cycle complete: %s", asyncio.run(run_once()))


if __name__ == "__main__":
    main()
