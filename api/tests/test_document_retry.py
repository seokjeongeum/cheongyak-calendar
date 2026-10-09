"""A new download pipeline retries today's failures once, retaining reviews."""
from __future__ import annotations

import copy
from datetime import date

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import init_db, make_engine
from app.extract.pipeline import DOCUMENT_PIPELINE_VERSION, _diagnostics_rule
from app.extract.official_rules import PARSER_VERSION
from app.ingest import worker
from app.models import DocumentExtractionState, Notice
from app.repository import upsert_notice
from test_repository_api import example_notice


@pytest.mark.asyncio
@pytest.mark.parametrize("status,version,parser_version,discovery_status,expected_attempts", [
    ("unreadable", None, PARSER_VERSION, None, 1),
    ("error", "older-download-pipeline", PARSER_VERSION, None, 1),
    ("unreadable", DOCUMENT_PIPELINE_VERSION, PARSER_VERSION, None, 0),
    ("partial", None, PARSER_VERSION, None, 0),
    ("complete", None, PARSER_VERSION, None, 0),
    ("partial", DOCUMENT_PIPELINE_VERSION, "older-parser", None, 1),
    ("unsupported", DOCUMENT_PIPELINE_VERSION, "older-parser", None, 1),
    ("complete", DOCUMENT_PIPELINE_VERSION, "older-parser", None, 0),
    ("partial", "older-download-pipeline", PARSER_VERSION, "error", 1),
    ("complete", "older-download-pipeline", PARSER_VERSION, "error", 1),
    ("partial", "older-download-pipeline", PARSER_VERSION, "resolved", 0),
    ("partial", DOCUMENT_PIPELINE_VERSION, PARSER_VERSION, "error", 0),
])
async def test_same_day_failure_gets_one_new_pipeline_retry_without_erasing_reviews(tmp_path, monkeypatch, status, version, parser_version, discovery_status, expected_attempts):
    today = date(2026, 10, 9)
    engine = make_engine(f"sqlite:///{tmp_path / 'retry.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "extraction_configured", lambda: False)
    row = example_notice()
    row["announcement_date"] = "2026-10-08"
    row["document_hash"] = "reviewed-same-bytes"
    reviewed = {"kind": "applicant_regions", "effect": "metadata", "source": "official_document_parser",
                "verification": "official", "document_hash": row["document_hash"],
                "scope_complete": True, "regions": [{"region_code": "41", "region_name": "경기도"}]}
    entries = ([{"stage": "discovery", "code": "announcement_download_failed", "status": discovery_status}]
               if discovery_status else [])
    row["rules"] += [reviewed, {**_diagnostics_rule(entries, status, row["document_hash"]),
                               "pipeline_version": version, "parser_version": parser_version}]
    with factory() as session:
        upsert_notice(session, row)
        session.add(DocumentExtractionState(source=row["source"], external_id=row["external_id"], audited_on=today))
        session.commit()
    attempts = []
    async def enrich(payload, **kwargs):
        attempts.append(kwargs["known_document_hash"])
        assert reviewed in payload["rules"]
        return {**payload, "rules": [r for r in payload["rules"] if r.get("kind") != "document_diagnostics"]
                + [_diagnostics_rule([], "unreadable", row["document_hash"])]}
    monkeypatch.setattr(worker, "enrich_notice", enrich)
    feed_row = {**row, "rules": [{"kind": "housing_classification", "effect": "metadata",
                                "housing_kind": "private", "verification": "official"}]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError("no network")))) as http:
        await worker._save_rows(row["source"], [copy.deepcopy(feed_row)], http, today)
        await worker._save_rows(row["source"], [copy.deepcopy(feed_row)], http, today)
    assert len(attempts) == expected_attempts
    with factory() as session:
        saved = session.scalar(select(Notice).where(Notice.external_id == row["external_id"]))
        assert saved.document_hash == row["document_hash"] and reviewed in saved.rules
        if expected_attempts:
            assert next(r for r in saved.rules if r.get("kind") == "document_diagnostics")["pipeline_version"] == DOCUMENT_PIPELINE_VERSION
        assert session.get(DocumentExtractionState, (row["source"], row["external_id"])).audited_on == today
    engine.dispose()
