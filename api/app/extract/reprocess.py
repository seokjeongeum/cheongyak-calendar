"""Bounded local-only reprocessing of retained public notice documents.

Example: python -m app.extract.reprocess --active --limit 50
No personal profiles are accepted and this command never calls Gemini.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy import func, or_, select

from app.db import SessionLocal
from app.models import DocumentExtractionState, Notice, NoticeEvent
from app.repository import NON_APPLICATION_KINDS, _existing_payload, lock_notice, open_ended_application_clause, upsert_notice, record_source_status
from .pipeline import enrich_notice
from .official_rules import PARSER_VERSION, parser_version_usable
from app.qualification import public_contract_schedule, requirements_complete


def _context(payload: dict) -> tuple:
    """Document identity and cutoff; current feed amounts/dates are separate."""
    rules = payload.get("rules", [])
    kind = next((r.get("housing_kind") for r in rules if r.get("kind") == "housing_classification" and r.get("verification") == "official"), None)
    original = next((r.get("value", {}).get("original_announcement_date") for r in rules if r.get("kind") == "qualification_context" and r.get("verification") == "official"), None)
    announced = str(payload.get("announcement_date"))
    return payload.get("official_url"), announced, kind, str(original or announced)


def _document_patch(current: dict, enriched: dict) -> dict:
    """Apply local document output to current data, never the downloaded snapshot."""
    digest = enriched.get("document_hash") or current.get("document_hash")
    changed = bool(digest and current.get("document_hash") and digest != current["document_hash"])
    local = [copy.deepcopy(r) for r in enriched.get("rules", [])
             if r.get("source") == "official_document_parser" and (r.get("document_hash") == digest or r.get("kind") == "document_diagnostics")
             and r.get("parser_version") == PARSER_VERSION]
    local = list({json.dumps(r, sort_keys=True, ensure_ascii=False): r for r in local}.values())
    # API metadata can change during the download. A parser context carries only
    # its new document cutoff/public-housing fact over the latest source flags.
    current_context = {}
    for rule in current.get("rules", []):
        if rule.get("kind") == "qualification_context" and rule.get("verification") == "official" and rule.get("source") != "official_document_parser":
            current_context.update(rule.get("value", {}))
    for rule in local:
        if rule.get("kind") == "qualification_context":
            document_context = {k: v for k, v in rule.get("value", {}).items()
                                if k in {"original_announcement_date", "application_announcement_date", "application_criterion_date", "application_criterion_basis"} or (k == "public_housing" and v is True)}
            rule["value"] = {**current_context, **document_context}
    parsed_document = any(r.get("kind") != "document_diagnostics" for r in local)
    rules = [copy.deepcopy(r) for r in current.get("rules", [])
             if (not parsed_document or r.get("source") != "official_document_parser") and r.get("kind") != "document_diagnostics"
             and parser_version_usable(r, category=current.get("category", ""), title=current.get("title", ""), rules=current.get("rules", []))
             and not (changed and (r.get("source") == "official_document_parser"
                                  or r.get("verification") in {"ai_unverified", "auto_unverified"}))]
    rules.extend(local)
    # The detail-page schedule has independent HTML provenance and no PDF
    # hash. Carry this refreshed public fact through the document-only patch.
    detail_schedules = [copy.deepcopy(r) for r in enriched.get("rules", []) if r.get("kind") == "contract_schedule"
                        and r.get("source") == "lh_official_detail" and r.get("verification") == "official"]
    if detail_schedules:
        rules = [r for r in rules if not (r.get("kind") == "contract_schedule" and r.get("source") == "lh_official_detail")] + detail_schedules
    patch = {"source": current["source"], "external_id": current["external_id"],
             "document_hash": digest, "rules": rules, "replace_rules": True,
             "rules_complete": requirements_complete(rules, current.get("rules_complete", False))}
    cap = next((r.get("value") for r in reversed(rules) if r.get("kind") == "price_cap" and r.get("verification") == "official"), None)
    if cap in {"yes", "no", "not_applicable"}:
        patch["price_cap_status"] = cap
    official = urlparse(str(current.get("official_url") or ""))
    query = parse_qs(official.query)
    if official.hostname == "apply.lh.or.kr" and (query.get("uppAisTpCd") or [""])[0] == "39" and (query.get("aisTpCd") or [""])[0] == "42":
        patch["category"] = "public_rental"
        patch["price_cap_status"] = "not_applicable"
    if changed:
        patch["prices"] = [p for p in current.get("prices", []) if p.get("verification") not in {"ai_unverified", "auto_unverified"}]
        patch["replace_prices"] = True
    verified_prices = [copy.deepcopy(p) for p in enriched.get("prices", []) if p.get("verification") == "official" and p.get("document_hash") == digest]
    if verified_prices:
        units = {p["unit_type"] for p in verified_prices}
        patch["prices"] = [p for p in current.get("prices", []) if p["unit_type"] not in units] + verified_prices
        patch["replace_prices"] = True
    return patch


def _finish(summary: dict, *, failed: bool = False) -> None:
    state = "error" if failed or (summary["failed"] and summary["failed"] == summary["attempted"]) else "partial" if summary["unsupported"] or summary["failed"] or summary["skipped"] or summary.get("missing_external_ids") else "ok"
    message = (f"{summary['attempted']}개 공고 확인 · 검증된 조건 {summary['verified_conditions']}개"
               f" · 자동 판독 범위 밖 {summary['unsupported']}개 · 변경으로 재확인 대기 {summary['skipped']}개 · 처리 실패 {summary['failed']}개")
    if summary.get("missing_external_ids"):
        message += f" · 저장된 원본이 없는 지정 공고 {len(summary['missing_external_ids'])}개"
    with SessionLocal() as session:
        record_source_status(session, "official_conditions", state, message, record_count=summary["updated"])
        session.commit()


async def reprocess(*, ids: list[str] | None = None, external_ids: list[str] | None = None, active: bool = False, limit: int = 50, dry_run: bool = False, sales_only: bool = False, all_targets: bool = False) -> dict:
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    statement = select(Notice.source, Notice.external_id).where(Notice.official_url.is_not(None))
    if ids:
        statement = statement.where(Notice.id.in_(ids))
    requested_external_ids = list(dict.fromkeys(external_ids or []))
    if any(not isinstance(value, str) or not value.strip() for value in requested_external_ids):
        raise ValueError("external_ids must contain nonempty official notice numbers")
    if requested_external_ids:
        statement = statement.where(Notice.external_id.in_(requested_external_ids))
    if sales_only:
        statement = statement.where(Notice.category.in_(["apt", "private_sale", "public_sale", "unsold", "optional_supply"]))
    if active:
        reception = select(NoticeEvent.id).where(NoticeEvent.notice_id == Notice.id,
            NoticeEvent.kind.not_in(NON_APPLICATION_KINDS),
            or_(func.coalesce(NoticeEvent.end_date, NoticeEvent.start_date) >= today, open_ended_application_clause())).exists()
        statement = statement.where(reception)
    statement = statement.order_by(Notice.announcement_date.desc(), Notice.id)
    if not all_targets:
        statement = statement.limit(max(1, min(limit, 100)))
    summary = {"attempted": 0, "updated": 0, "verified_conditions": 0, "unsupported": 0, "skipped": 0, "failed": 0, "missing_external_ids": []}
    records = []
    logging.getLogger("httpx").setLevel(logging.WARNING)
    with SessionLocal() as session:
        if requested_external_ids:
            retained_ids = set(session.scalars(select(Notice.external_id).where(Notice.external_id.in_(requested_external_ids))))
            summary["missing_external_ids"] = [value for value in requested_external_ids if value not in retained_ids]
        targets = list(session.execute(statement).all())
        if not dry_run:
            record_source_status(session, "official_conditions", "running", "공개 공고문 조건 정리 중")
            session.commit()
    try:
        async with httpx.AsyncClient(timeout=45, headers={"User-Agent": "CheongyakCalendar/1.0 (official public document parser)"}) as client:
            for source, external_id in targets:
                summary["attempted"] += 1
                try:
                    # Release the read transaction before public network requests.
                    with SessionLocal() as session:
                        notice = session.scalar(select(Notice).where(Notice.source == source, Notice.external_id == external_id))
                        if notice is None:
                            summary["skipped"] += 1
                            continue
                        snapshot = copy.deepcopy(_existing_payload(notice))
                    enriched = await enrich_notice(copy.deepcopy(snapshot), client=client, known_document_hash=snapshot.get("document_hash"), allow_gemini=False)
                    # The feed worker may have committed prices/schedules while the
                    # document was downloading. Refresh under the same identity lock.
                    with SessionLocal() as session:
                        fresh = lock_notice(session, source, external_id)
                        if fresh is None:
                            summary["skipped"] += 1
                            continue
                        current = _existing_payload(fresh)
                        if _context(snapshot) != _context(current) or current.get("document_hash") not in {snapshot.get("document_hash"), enriched.get("document_hash")}:
                            summary["skipped"] += 1
                            continue
                        patch = _document_patch(current, enriched)
                        conditions = [r for r in patch["rules"] if r.get("source") == "official_document_parser" and r.get("effect") != "metadata"]
                        changed = patch["rules"] != current["rules"] or patch.get("document_hash") != current.get("document_hash") or ("prices" in patch and patch["prices"] != current.get("prices", [])) or ("category" in patch and patch["category"] != current.get("category"))
                        if changed:
                            if not dry_run:
                                upsert_notice(session, patch)
                        if not dry_run:
                            state = session.get(DocumentExtractionState, (source, external_id), populate_existing=True)
                            if state is None:
                                state = DocumentExtractionState(source=source, external_id=external_id)
                                session.add(state)
                            state.audited_on = today
                            session.commit()
                        summary["verified_conditions"] += len(conditions)
                        summary["unsupported"] += not bool(conditions)
                        summary["updated"] += changed
                        records.append({"notice_id": fresh.id, "title": current.get("title"), "source": source,
                            "document_hash": patch.get("document_hash"), "verified_condition_count": len(conditions),
                            "offered_supplies": [r.get("supplies") for r in patch["rules"] if r.get("kind") == "offered_supplies" and r.get("document_hash")],
                            "condition_coverage": [r.get("scopes") for r in patch["rules"] if r.get("kind") == "condition_coverage"],
                            "contract_schedule": public_contract_schedule(patch["rules"], contract_events=[
                                {**event, "source": source, "evidence_url": current.get("official_url")}
                                for event in current.get("events", []) if event.get("kind") == "contract"
                            ]).model_dump(mode="json"),
                            "document_diagnostics": [r.get("diagnostics") for r in patch["rules"] if r.get("kind") == "document_diagnostics"]})
                except Exception as exc:
                    summary["failed"] += 1
                    records.append({"source":source,"external_id":external_id,"status":"failed","failure_type":type(exc).__name__})
                    logging.getLogger(__name__).warning("Local document reprocessing failed for %s: %s", source, type(exc).__name__)
                # Avoid bursts on public document servers even in a manual run.
                await asyncio.sleep(0.15)
    except BaseException:
        if not dry_run:
            _finish(summary, failed=True)
        raise
    if not dry_run:
        _finish(summary)
    return {**summary,"records":records}


def main() -> None:
    parser = argparse.ArgumentParser(description="Reprocess retained official public notice conditions without Gemini")
    parser.add_argument("--notice-id", action="append", default=[], help="Retained notice UUID; repeat for multiple notices")
    parser.add_argument("--external-id", action="append", default=[], help="Official notice number; repeat for multiple notices. Missing retained originals are reported.")
    parser.add_argument("--active", action="store_true", help="Only notices with current/future application reception")
    parser.add_argument("--limit", type=int, default=50, help="Bounded notice count, at most 100")
    parser.add_argument("--dry-run", action="store_true", help="Download and compare without writing notices")
    parser.add_argument("--sales-only", action="store_true", help="Only private/public sale and apartment residual notices")
    parser.add_argument("--all", action="store_true", help="Process every matching retained notice")
    parser.add_argument("--report", help="Write the per-notice audit JSON to this path")
    args = parser.parse_args()
    summary = asyncio.run(reprocess(ids=args.notice_id, external_ids=args.external_id, active=args.active, limit=args.limit, dry_run=args.dry_run, sales_only=args.sales_only, all_targets=args.all))
    if args.report:
        from pathlib import Path
        Path(args.report).write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k!="records"},ensure_ascii=False))


if __name__ == "__main__":
    main()
