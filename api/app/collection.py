"""Owner-triggered collection using the same durable lease as scheduled runs.

Only public feed work is passed to the worker. Credentials are read from the
existing server store; neither request bodies nor keys are process arguments.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import SessionLocal
from app.hosted_runner import _shutdown
from app.integration_settings import require_admin
from app.models import CollectionRun, SourceStatus

LOGGER = logging.getLogger("cheongyak.collection")
NAME = "current"
LEASE_SECONDS = 10 * 60
HEARTBEAT_SECONDS = 30
router = APIRouter(prefix="/api/collection", tags=["공식 공고 수집"])


class CollectionPublic(BaseModel):
    job_id: str | None = None
    status: Literal["idle", "running", "completed", "error", "interrupted"] = "idle"
    trigger: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    message: str = "수집을 시작하지 않았습니다."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _public(row: CollectionRun | None) -> CollectionPublic:
    if row is None:
        return CollectionPublic()
    def utc(value: datetime | None) -> datetime | None:
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value

    return CollectionPublic(
        job_id=row.job_id, status=row.status, trigger=row.trigger,
        started_at=utc(row.started_at), finished_at=utc(row.finished_at),
        message=row.message or "수집 상태를 확인합니다.",
    )


def _interrupt_sources(session, now: datetime) -> None:
    started = session.scalar(select(CollectionRun.started_at).where(CollectionRun.name == NAME))
    if started is not None:
        session.execute(update(SourceStatus).where(
            SourceStatus.status == "running", SourceStatus.last_attempt_at >= started,
            SourceStatus.last_attempt_at <= now,
        ).values(status="error", message="수집 실행이 중단되었습니다. 기존 자료를 유지하며 다음 수집에서 다시 확인합니다."))


def _expire_collection(session, now: datetime) -> None:
    result = session.execute(update(CollectionRun).where(
        CollectionRun.name == NAME, CollectionRun.status == "running",
        or_(CollectionRun.lease_expires_at <= now, CollectionRun.lease_expires_at.is_(None)),
    ).values(status="interrupted", finished_at=now, message="수집 실행이 중단되었습니다. 다시 수집할 수 있습니다."))
    if result.rowcount == 1:
        _interrupt_sources(session, now)


def collection_state() -> CollectionPublic:
    """A killed host cannot leave a job appearing to run indefinitely."""
    now = _now()
    with SessionLocal() as session:
        _expire_collection(session, now)
        session.commit()
        return _public(session.get(CollectionRun, NAME))


def claim_collection(trigger: str) -> tuple[CollectionPublic, bool]:
    """Atomic across API replicas and the external three-hour worker."""
    now = _now()
    job_id = str(uuid4())
    with SessionLocal() as session:
        insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
        session.execute(insert(CollectionRun).values(name=NAME, status="idle").on_conflict_do_nothing(index_elements=[CollectionRun.name]))
        _expire_collection(session, now)
        result = session.execute(update(CollectionRun).where(
            CollectionRun.name == NAME,
            or_(CollectionRun.status != "running", CollectionRun.lease_expires_at <= now, CollectionRun.lease_expires_at.is_(None)),
        ).values(
            job_id=job_id, status="running", trigger=trigger, started_at=now,
            finished_at=None, lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
            message="공식 공고와 경쟁률을 수집하고 있습니다.",
        ))
        session.commit()
        return _public(session.get(CollectionRun, NAME)), result.rowcount == 1


def renew_collection(job_id: str) -> bool:
    with SessionLocal() as session:
        result = session.execute(update(CollectionRun).where(
            CollectionRun.name == NAME, CollectionRun.job_id == job_id,
            CollectionRun.status == "running", CollectionRun.lease_expires_at > _now(),
        ).values(lease_expires_at=_now() + timedelta(seconds=LEASE_SECONDS)))
        session.commit()
        return result.rowcount == 1


def finish_collection(job_id: str, status: str, message: str) -> None:
    # A late child may never replace the state of a newer job.
    with SessionLocal() as session:
        now = _now()
        result = session.execute(update(CollectionRun).where(
            CollectionRun.name == NAME, CollectionRun.job_id == job_id,
            CollectionRun.status == "running",
        ).values(status=status, finished_at=now, lease_expires_at=None, message=message))
        if result.rowcount == 1 and status in {"error", "interrupted"}:
            _interrupt_sources(session, now)
        session.commit()


class CollectionHeartbeat:
    """Keep the lease alive even while a PDF parser blocks the asyncio loop."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        last_success = monotonic()
        while not self.stopped.wait(HEARTBEAT_SECONDS):
            try:
                renewed = renew_collection(self.job_id)
                if self.stopped.is_set():
                    return
                if not renewed:
                    # Losing ownership means this worker must stop before a
                    # replacement worker can write the same official feeds.
                    os.kill(os.getpid(), signal.SIGTERM)
                    return
                last_success = monotonic()
            except Exception as error:
                if self.stopped.is_set():
                    return
                LOGGER.warning("Collection heartbeat failed: %s", type(error).__name__)
                if monotonic() - last_success >= LEASE_SECONDS:
                    os.kill(os.getpid(), signal.SIGTERM)
                    return

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stopped.set()
        self.thread.join(timeout=2)


class ManualCollector:
    """Track only this API process's child; shared ownership is in PostgreSQL."""

    def __init__(self):
        self.lock = threading.Lock()
        self.processes: dict[str, subprocess.Popen] = {}
        self.stopping = False

    def startup(self) -> None:
        with self.lock:
            self.stopping = False

    def start(self, job_id: str) -> None:
        try:
            with self.lock:
                if self.stopping:
                    raise RuntimeError()
                process = subprocess.Popen(
                    [sys.executable, "-m", "app.ingest.worker", "--once", "--job-id", job_id],
                    start_new_session=True, stdin=subprocess.DEVNULL,
                    # Worker results are recorded in coverage/job tables.
                    # Never relay arbitrary subprocess text to public users.
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self.processes[job_id] = process
            threading.Thread(target=self._watch, args=(job_id, process), daemon=True).start()
        except Exception as error:
            LOGGER.error("Collection process could not start: %s", type(error).__name__)
            finish_collection(job_id, "error", "수집 실행을 시작하지 못했습니다. 다시 시도하세요.")

    def _watch(self, job_id: str, process: subprocess.Popen) -> None:
        code = process.wait()
        try:
            # Normal workers finish their own state, so this is only a safe
            # fallback for startup errors or an abrupt child termination.
            finish_collection(job_id, "completed" if code == 0 else "error",
                              "수집을 마쳤습니다. 출처별 결과를 확인하세요." if code == 0 else "수집 실행이 실패했습니다. 출처별 상태를 확인하고 다시 시도하세요.")
        except Exception as error:
            LOGGER.warning("Collection completion state failed: %s", type(error).__name__)
        finally:
            with self.lock:
                self.processes.pop(job_id, None)

    def shutdown(self) -> None:
        with self.lock:
            self.stopping = True
            processes = dict(self.processes)
        for job_id in processes:
            try:
                finish_collection(job_id, "interrupted", "서버 종료로 수집이 중단되었습니다. 다시 수집할 수 있습니다.")
            except Exception as error:
                LOGGER.warning("Collection shutdown state failed: %s", type(error).__name__)
        _shutdown(list(processes.values()), 10)


manual_collector = ManualCollector()


@router.get("", response_model=CollectionPublic)
def get_collection(response: Response) -> CollectionPublic:
    response.headers["Cache-Control"] = "no-store"
    return collection_state()


@router.post("", status_code=202, response_model=CollectionPublic, dependencies=[Depends(require_admin)])
def start_collection(response: Response) -> CollectionPublic:
    response.headers["Cache-Control"] = "no-store"
    state, claimed = claim_collection("manual")
    if claimed:
        manual_collector.start(state.job_id)
        return collection_state()
    return state
