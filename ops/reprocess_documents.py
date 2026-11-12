"""Run a pinned, public-document review through the existing collector workflow."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import subprocess
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo


BATCH_SIZE = 50
REQUEST_PATH = "ops/document-reprocess/*.json"
TOTALS = ("attempted", "updated", "verified_conditions", "unsupported", "skipped", "failed")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def request_for_revision() -> tuple[str, bool, list[str], list[str]]:
    revision = git("rev-parse", "HEAD")
    if os.environ.get("GITHUB_EVENT_NAME") != "push":
        ids = [str(UUID(value.strip())) for value in os.environ.get("NOTICE_IDS", "").split(",") if value.strip()]
        return revision, not ids, ids, []

    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    before = event.get("before", "")
    if (event.get("ref") != "refs/heads/work" or event.get("after") != revision
            or not re.fullmatch(r"[0-9a-f]{40}", before)
            or git("rev-parse", "HEAD^") != before):
        raise ValueError("The review request must be a single commit on work.")
    paths = git("diff", "--name-status", before, revision).splitlines()
    if len(paths) != 1 or not re.fullmatch(r"A\tops/document-reprocess/[\w-]+\.json", paths[0]):
        raise ValueError(f"The review commit must only add one {REQUEST_PATH} request.")
    manifest = json.loads(Path(paths[0].split("\t", 1)[1]).read_text())
    if set(manifest) != {"deployed_revision", "include_active", "notice_ids", "external_ids"}:
        raise ValueError("Unrecognized document review request fields.")
    if manifest["deployed_revision"] != before or type(manifest["include_active"]) is not bool:
        raise ValueError("The review request does not match the deployed revision.")
    if not isinstance(manifest["notice_ids"], list) or not isinstance(manifest["external_ids"], list):
        raise ValueError("Notice identifiers must be lists.")
    ids = [str(UUID(value)) for value in manifest["notice_ids"]]
    external_ids = manifest["external_ids"]
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9]{10,20}", value) for value in external_ids):
        raise ValueError("External identifiers must be official notice numbers.")
    if not (manifest["include_active"] or ids or external_ids):
        raise ValueError("The review request contains no targets.")
    return revision, manifest["include_active"], ids, external_ids


def select_originals(session, *, include_active: bool, ids: list[str], external_ids: list[str]) -> tuple[list[dict], dict]:
    from sqlalchemy import or_, select
    from app.main import list_notices
    from app.models import Notice

    active_ids: set[str] = set()
    if include_active:
        # Apply the same dates, corrections and rental exclusions as the public
        # calendar, then expand the results back to the retained source rows.
        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        page = 1
        while True:
            result = list_notices(start=today, exclude_public_rental=True, application_only=True,
                                  page=page, page_size=100, session=session)
            active_ids.update(notice.id for notice in result.items)
            if page * result.page_size >= result.total:
                break
            page += 1

    identity = select(Notice.id, Notice.duplicate_of_id, Notice.external_id, Notice.source,
                      Notice.title, Notice.official_url.is_not(None).label("has_official_url"))
    requested = session.execute(identity.where(or_(Notice.id.in_(ids), Notice.external_id.in_(external_ids)))).all()
    canonical_ids = active_ids | {row.duplicate_of_id or row.id for row in requested}
    rows = session.execute(identity.where(or_(Notice.id.in_(canonical_ids), Notice.duplicate_of_id.in_(canonical_ids)))
                           .order_by(Notice.id)).all()
    targets = [{
        "notice_id": row.id, "canonical_id": row.duplicate_of_id or row.id, "source": row.source,
        "external_id": row.external_id, "title": row.title, "has_official_url": row.has_official_url,
    } for row in rows]
    return targets, {
        "active_public_notice_ids": sorted(active_ids),
        "missing_notice_ids": sorted(set(ids) - {row.id for row in requested}),
        "missing_external_ids": sorted(set(external_ids) - {row.external_id for row in requested}),
    }


def price_snapshots(session, ids: list[str]) -> dict:
    from sqlalchemy import select
    from app.models import Notice
    from app.repository import notice_public

    snapshots = {}
    for notice in session.scalars(select(Notice).where(Notice.id.in_(ids))):
        snapshots[notice.id] = {
            "stored_prices": [{
                "unit_type": p.unit_type, "area_sqm": p.area_sqm, "price_kind": p.price_kind,
                "amount_krw": p.amount_krw, "monthly_krw": p.monthly_krw, "verification": p.verification,
                "basis_label": p.basis_label, "document_hash": p.document_hash,
            } for p in notice.prices],
            "version": notice.version,
        }
        try:
            public = notice_public([notice])
            snapshots[notice.id]["public_prices"] = [p.model_dump(mode="json") for p in public.prices]
            snapshots[notice.id]["additional_costs"] = [cost.model_dump(mode="json") for cost in public.additional_costs]
        except Exception as error:
            snapshots[notice.id]["projection_failure"] = type(error).__name__
    return snapshots


def save_report(path: Path, report: dict) -> None:
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    pending.replace(path)


def summarize_run(path: Path) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path or not path.exists():
        return
    report = json.loads(path.read_text())
    totals = report["totals"]
    changes = sum(len(batch["price_changes"]) for batch in report["batches"])
    with Path(summary_path).open("a") as summary:
        summary.write(
            "### 공식 공고문 재처리\n\n"
            f"- 공개 일정 {len(report['active_public_notice_ids'])}건, 수집 원본 {len(report['originals'])}건\n"
            f"- 완료 배치 {len(report['batches'])}개, 확인 시도 {totals['attempted']}건\n"
            f"- 확보 조건 {totals['verified_conditions']}개, 가격 변경 {changes}건\n"
            f"- 판독 범위 밖 {totals['unsupported']}건, 재확인 대기 {totals['skipped']}건, 처리 실패 {totals['failed']}건\n\n"
            "공고별 근거·처리 단계와 가격 변경 내역은 `public-document-review`에 있습니다.\n"
        )


async def run(report_path: Path) -> bool:
    from app.db import SessionLocal, collector_session_limits
    from app.extract.official_rules import PARSER_VERSION
    from app.extract.price_tables import PRICE_PARSER_VERSION
    from app.extract.reprocess import _finish, reprocess

    revision, include_active, ids, external_ids = request_for_revision()
    with collector_session_limits(SessionLocal):
        with SessionLocal() as session:
            targets, scope = select_originals(session, include_active=include_active, ids=ids, external_ids=external_ids)
        report = {"revision": revision, "parser_version": PARSER_VERSION, "price_parser_version": PRICE_PARSER_VERSION,
                  **scope, "originals": targets, "batches": [], "totals": dict.fromkeys(TOTALS, 0)}
        save_report(report_path, report)
        for target in targets:
            if not target["has_official_url"]:
                target["status"] = "missing_official_url"
        by_id = {target["notice_id"]: target for target in targets}
        work = [target["notice_id"] for target in targets if target["has_official_url"]]
        if not work:
            save_report(report_path, report)
            logging.error("No retained public notices with an official URL matched the request.")
            return False

        for offset in range(0, len(work), BATCH_SIZE):
            batch = work[offset:offset + BATCH_SIZE]
            with SessionLocal() as session:
                before = price_snapshots(session, batch)
            result = await reprocess(ids=batch, limit=BATCH_SIZE)
            reviewed = {record.get("notice_id") for record in result["records"]}
            failed = {(record["source"], record.get("external_id")): record.get("failure_type")
                      for record in result["records"] if record.get("status") == "failed"}
            with SessionLocal() as session:
                after = price_snapshots(session, batch)
            changes = {}
            for notice_id in batch:
                target = by_id[notice_id]
                failure = failed.get((target["source"], target["external_id"]))
                target["status"] = ("failed" if failure else "reviewed" if notice_id in reviewed
                                    else "removed_or_changed_during_review")
                previous, current = before.get(notice_id), after.get(notice_id)
                if previous is None or current is None or any(
                        previous.get(key) != current.get(key)
                        for key in ("stored_prices", "public_prices", "additional_costs", "projection_failure")):
                    changes[notice_id] = {"before": previous, "after": current}
            report["batches"].append({"notice_ids": batch, **result, "price_changes": changes})
            for key in TOTALS:
                report["totals"][key] += result[key]
            save_report(report_path, report)
            logging.warning("Batch %d of %d complete: %d originals, %d price changes",
                            1 + offset // BATCH_SIZE, (len(work) + BATCH_SIZE - 1) // BATCH_SIZE,
                            len(batch), len(changes))
        _finish({**report["totals"], "missing_external_ids": scope["missing_external_ids"]})
    return report["totals"]["failed"] == 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "WARNING"))
    try:
        if not asyncio.run(run(args.report)):
            raise SystemExit(1)
    except Exception as error:
        # Database/transport exceptions can include private connection details.
        logging.error("Document review failed: %s", type(error).__name__)
        raise SystemExit(1) from None
    finally:
        summarize_run(args.report)


if __name__ == "__main__":
    main()
