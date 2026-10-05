"""Local audits must preserve concurrent authoritative feed updates."""

from datetime import date
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from app.db import init_db, make_engine
from app.extract import reprocess
from app.extract.official_rules import PARSER_VERSION
from app.extract.official_rules import parse_official_rules
from app.ingest import worker
from app.models import DocumentExtractionState, SourceStatus, NoticeRevision
from app.repository import lock_notice, upsert_notice, notice_public


@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(reprocess, "SessionLocal", factory)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(worker, "extraction_configured", lambda: False)
    yield factory
    engine.dispose()


def feed(**changes):
    return {"source": "cheongyak_home", "external_id": "public-1", "title": "공식 모집공고",
            "category": "private_sale", "announcement_date": "2026-10-02",
            "official_url": "https://www.applyhome.co.kr/notice/1", "document_hash": "old-file",
            "rules": [{"kind": "housing_classification", "effect": "metadata", "housing_kind": "private", "verification": "official", "source": "official_api"},
                      {"kind": "qualification_context", "effect": "metadata", "verification": "official", "source": "official_api", "value": {"speculation_zone": False}}],
            "prices": [{"unit_type": "84A", "amount_krw": 600_000_000, "price_kind": "sale_max", "verification": "official"}],
            "events": [{"kind": "general", "start_date": "2026-10-12", "end_date": "2026-10-13"}], **changes}


def document_rule(digest="new-file"):
    return {"id": "reviewed-condition", "kind": "private_rank_months", "value": 6,
            "verification": "official", "source": "official_document_parser", "document_hash": digest,
            "parser_version": PARSER_VERSION,
            "criterion_date": "2026-10-02", "evidence_page": 1,
            "evidence_url": "https://www.applyhome.co.kr/public.pdf", "evidence_text": "청약통장 가입기간 6개월 이상"}


def seed(store, **changes):
    with store() as session:
        notice = upsert_notice(session, feed(**changes))
        session.commit()
        return notice.id


@pytest.mark.asyncio
async def test_audit_merges_document_only_after_concurrent_feed_and_is_idempotent(store, monkeypatch):
    notice_id = seed(store)
    calls = 0

    async def download(snapshot, **kwargs):
        nonlocal calls
        calls += 1
        assert kwargs["allow_gemini"] is False
        if calls == 1:
            with store() as session:
                upsert_notice(session, {**feed(), "prices": [{"unit_type": "84A", "amount_krw": 610_000_000, "verification": "official", "price_kind": "sale_max"}],
                    "events": [{"kind": "general", "start_date": "2026-10-14", "end_date": "2026-10-15"}],
                    "rules": [feed()["rules"][0], {**feed()["rules"][1], "value": {"speculation_zone": True}}]})
                session.add(DocumentExtractionState(source="cheongyak_home", external_id="public-1", audited_on=date(2026, 10, 3)))
                session.commit()
        return {**snapshot, "document_hash": "new-file", "rules": [*snapshot["rules"], document_rule()], "replace_rules": True}

    monkeypatch.setattr(reprocess, "enrich_notice", download)
    first = await reprocess.reprocess(ids=[notice_id])
    assert (first["updated"], first["failed"], first["verified_conditions"]) == (1, 0, 1)
    with store() as session:
        notice = lock_notice(session, "cheongyak_home", "public-1")
        assert notice.prices[0].amount_krw == 610_000_000
        assert notice.events[0].start_date == date(2026, 10, 14)
        assert next(r for r in notice.rules if r["kind"] == "qualification_context")["value"]["speculation_zone"] is True
        version = notice.version
        assert session.get(SourceStatus, "official_conditions").status == "ok"
    second = await reprocess.reprocess(ids=[notice_id])
    assert second["updated"] == 0 and second["failed"] == 0
    with store() as session:
        assert lock_notice(session, "cheongyak_home", "public-1").version == version


@pytest.mark.asyncio
@pytest.mark.parametrize("correction", [
    {"official_url": "https://www.applyhome.co.kr/corrected/1"},
    {"announcement_date": "2026-10-03"},
    {"document_hash": "concurrent-corrected-file"},
])
async def test_changed_document_identity_skips_old_download(store, monkeypatch, correction):
    notice_id = seed(store)

    async def download(snapshot, **kwargs):
        with store() as session:
            upsert_notice(session, {"source": "cheongyak_home", "external_id": "public-1", **correction})
            session.commit()
        return {**snapshot, "document_hash": "new-file", "rules": [document_rule()]}

    monkeypatch.setattr(reprocess, "enrich_notice", download)
    result = await reprocess.reprocess(ids=[notice_id])
    assert result["skipped"] == 1 and result["updated"] == 0
    with store() as session:
        notice = lock_notice(session, "cheongyak_home", "public-1")
        assert not any(r.get("source") == "official_document_parser" for r in notice.rules)
        assert notice.prices[0].amount_krw == 600_000_000
        assert session.get(SourceStatus, "official_conditions").status == "partial"


@pytest.mark.asyncio
async def test_failed_audit_finishes_coverage_without_leaking_error_data(store, monkeypatch):
    notice_id = seed(store)

    async def broken(*args, **kwargs):
        raise RuntimeError("private-key-in-query")

    monkeypatch.setattr(reprocess, "enrich_notice", broken)
    result = await reprocess.reprocess(ids=[notice_id])
    assert result["failed"] == 1 and result["updated"] == 0
    with store() as session:
        status = session.get(SourceStatus, "official_conditions")
        assert status.status == "error" and "private-key" not in status.message
        assert lock_notice(session, "cheongyak_home", "public-1").document_hash == "old-file"


@pytest.mark.asyncio
async def test_old_parser_facts_are_retired_even_if_same_hash_cannot_be_reparsed(store, monkeypatch):
    old = {**document_rule("old-file"), "parser_version": "official-sections-2026-10-03-v1"}
    notice_id = seed(store, rules=[*feed()["rules"], old])

    async def unchanged_after_download_failure(snapshot, **kwargs):
        return snapshot

    monkeypatch.setattr(reprocess, "enrich_notice", unchanged_after_download_failure)
    result = await reprocess.reprocess(ids=[notice_id])
    assert result["updated"] == 1 and result["unsupported"] == 1
    with store() as session:
        notice = lock_notice(session, "cheongyak_home", "public-1")
        assert not any(r.get("source") == "official_document_parser" for r in notice.rules)
        assert notice.document_hash == "old-file" and notice.prices[0].amount_krw == 600_000_000
        assert session.get(SourceStatus, "official_conditions").status == "partial"


@pytest.mark.asyncio
async def test_worker_refreshes_concurrent_state_and_does_not_revert_corrected_hash(store, monkeypatch):
    seed(store)

    async def stale_download(snapshot, **kwargs):
        with store() as session:
            upsert_notice(session, {"source": "cheongyak_home", "external_id": "public-1", "document_hash": "corrected-file", "rules": [document_rule("corrected-file")]})
            session.add(DocumentExtractionState(source="cheongyak_home", external_id="public-1", audited_on=date(2026, 10, 3)))
            session.commit()
        return {**snapshot, "document_hash": "stale-file", "rules": [document_rule("stale-file")]}

    monkeypatch.setattr(worker, "enrich_notice", stale_download)
    async with httpx.AsyncClient() as client:
        result = await worker._save_rows("cheongyak_home", [feed(document_hash=None)], client, date(2026, 10, 3))
    assert result[0] == 1 and result[1] == 0
    with store() as session:
        notice = lock_notice(session, "cheongyak_home", "public-1")
        assert notice.document_hash == "corrected-file"
        assert next(r for r in notice.rules if r.get("source") == "official_document_parser")["document_hash"] == "corrected-file"
        assert session.get(DocumentExtractionState, ("cheongyak_home", "public-1")).audited_on is None


@pytest.mark.asyncio
async def test_same_hash_jamsil_reprocess_repairs_prices_retains_history_and_is_idempotent(store, monkeypatch):
    fixture = next(f for f in json.loads((Path(__file__).parent / "fixtures/official-rules-v3.json").read_text()) if f["house_manage_no"] == "2026950085")
    parsed = parse_official_rules(fixture["pages"], url=fixture["document_url"], digest=fixture["document_hash"])
    notice_id = seed(store, document_hash=fixture["document_hash"], category="officetel", rules=[],
                     prices=[{"unit_type": "28D", "price_kind": "deposit", "amount_krw": None, "verification": "unknown"}])

    async def local(snapshot, **kwargs):
        assert kwargs["allow_gemini"] is False
        return {**snapshot, "rules": parsed["rules"], "prices": parsed["prices"]}

    monkeypatch.setattr(reprocess, "enrich_notice", local)
    assert (await reprocess.reprocess(ids=[notice_id]))["updated"] == 1
    with store() as session:
        notice = lock_notice(session, "cheongyak_home", "public-1")
        assert len(notice.prices) == 4 and notice.document_hash == fixture["document_hash"]
        assert {p.unit_type: p.amount_krw for p in notice.prices}["28D"] == 588000000
        assert notice_public([notice]).housing_kind == "not_applicable"
        assert notice.revisions[0].payload["prices"][0]["price_kind"] == "deposit"
        assert len(notice.revisions) == 2
    assert (await reprocess.reprocess(ids=[notice_id]))["updated"] == 0


@pytest.mark.asyncio
async def test_unsupported_lh_doc_still_repairs_happiness_rental_and_retains_revision(store, monkeypatch):
    notice_id = seed(store, source="lh", category="public_sale", official_url="https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do?uppAisTpCd=39&aisTpCd=42")

    async def unsupported(snapshot, **kwargs):
        return snapshot

    monkeypatch.setattr(reprocess, "enrich_notice", unsupported)
    assert (await reprocess.reprocess(ids=[notice_id]))["updated"] == 1
    with store() as session:
        notice = lock_notice(session, "lh", "public-1")
        assert notice.category == "public_rental"
        assert notice.revisions[0].payload["category"] == "public_sale"
        assert len(notice.revisions) == 2
