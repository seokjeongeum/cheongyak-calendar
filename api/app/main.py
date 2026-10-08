"""Read-only public API for official housing notice data."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.exception_handlers import request_validation_exception_handler
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db import get_session, init_db
from app.integration_settings import router as integrations_router
from app.models import Notice, NoticeEvent
from app.repository import NON_APPLICATION_KINDS, canonical_id, notice_matches_window, notice_public, open_ended_application_clause, related_notices, source_coverage
from app.schemas import CoveragePublic, HealthPublic, NoticeDetail, NoticePage, NoticePublic, SourceStatusPublic


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="주택청약 캘린더 API", version="0.1.0", lifespan=lifespan,
    docs_url="/api/docs", openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "PUT"],
    allow_headers=["Accept", "Content-Type", "Authorization"],
)
app.include_router(integrations_router)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Standard validation errors echo submitted inputs, including secrets.
    if request.url.path == "/api/integrations":
        return JSONResponse(status_code=422, content={"detail": "연결 설정 형식을 확인하세요."}, headers={"Cache-Control": "no-store"})
    return await request_validation_exception_handler(request, exc)


@app.get("/health", response_model=HealthPublic)
def health() -> HealthPublic:
    return HealthPublic(status="ok")


@app.get("/api/health", response_model=HealthPublic)
def api_health() -> HealthPublic:
    return HealthPublic(status="ok")


def _date_match(start: date | None, end: date | None, *, application_only: bool = False):
    application_predicates = [NoticeEvent.notice_id == Notice.id, NoticeEvent.kind.not_in(NON_APPLICATION_KINDS)]
    event_predicates = list(application_predicates)
    announcement_predicates = []
    if start is not None:
        event_predicates.append(or_(func.coalesce(NoticeEvent.end_date, NoticeEvent.start_date) >= start, open_ended_application_clause()))
        announcement_predicates.append(Notice.announcement_date >= start)
    if end is not None:
        event_predicates.append(NoticeEvent.start_date <= end)
        announcement_predicates.append(Notice.announcement_date <= end)
    matching_application = select(NoticeEvent.id).where(and_(*event_predicates)).exists()
    if application_only:
        return matching_application
    has_application = select(NoticeEvent.id).where(and_(*application_predicates)).exists()
    return or_(matching_application, and_(~has_application, *announcement_predicates))


@app.get("/api/notices", response_model=NoticePage)
def list_notices(
    start: date | None = None,
    end: date | None = None,
    category: str | None = None,
    cap_only: bool = False,
    exclude_public_rental: bool = False,
    application_only: bool = False,
    view: Literal["schedule", "results"] = "schedule",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> NoticePage:
    if start and end and end < start:
        raise HTTPException(status_code=422, detail="end must be on or after start")
    # Results use the same official reception-period overlap as the calendar,
    # including when a caller omits application_only or the date bounds.
    application_only = application_only or view == "results"
    query = select(Notice)
    if start is not None or end is not None or application_only:
        query = query.where(_date_match(start, end, application_only=application_only))
    matching = session.scalars(query).all()
    superseded_notices = session.scalars(select(Notice).where(Notice.id.in_(
        select(Notice.correction_of_id).where(Notice.correction_of_id.is_not(None))
    ))).all()
    superseded_ids = {canonical_id(item) for item in superseded_notices}
    corrected_refs = set(session.execute(select(Notice.source, Notice.correction_of_external_id).where(
        Notice.correction_of_external_id.is_not(None)
    )).all())
    canonical_ids = {item.duplicate_of_id or item.id for item in matching} - superseded_ids
    if not canonical_ids:
        return NoticePage(items=[], total=0, page=page, page_size=page_size)
    canonical = [
        item for item in session.scalars(select(Notice).where(Notice.id.in_(canonical_ids))).all()
        if (item.source, item.external_id) not in corrected_refs
    ]
    notices: list[NoticePublic] = [notice_public(related_notices(session, item), start=start, end=end) for item in canonical]
    notices = [item for item in notices if notice_matches_window(item, start, end, application_only=application_only)]
    if category:
        notices = [item for item in notices if item.category == category]
    if exclude_public_rental:
        notices = [item for item in notices if item.category != "public_rental"]
    if cap_only:
        notices = [item for item in notices if item.price_cap_status == "yes"]
    if view == "results":
        # Availability is based on saved official rows, not current freshness,
        # success status or eligibility. All filters precede total/pagination.
        notices = [item for item in notices if any(row.verification == "official" for row in item.competitions)]
        notices.sort(key=lambda item: (-(item.application_end_date or date.min).toordinal(), item.title, item.id))
    else:
        notices.sort(key=lambda item: (item.sort_date or date.max, item.title, item.id))
    total = len(notices)
    offset = (page - 1) * page_size
    return NoticePage(items=notices[offset : offset + page_size], total=total, page=page, page_size=page_size)


@app.get("/api/notices/{notice_id}", response_model=NoticeDetail)
def get_notice(notice_id: str, session: Session = Depends(get_session)) -> NoticeDetail:
    notice = session.get(Notice, notice_id)
    if notice is None:
        raise HTTPException(status_code=404, detail="Notice not found")
    return notice_public(related_notices(session, notice), detail=True)


@app.get("/api/coverage", response_model=CoveragePublic)
def get_coverage(session: Session = Depends(get_session)) -> CoveragePublic:
    return CoveragePublic(sources=[SourceStatusPublic.model_validate(item, from_attributes=True) for item in source_coverage(session)])
