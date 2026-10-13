"""Verified whole-source review replaces uncertain conditions, not source data."""
import copy
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import init_db, make_engine
from app.extract import pipeline
from app.extract.official_rules import PARSER_VERSION, parse_official_rules
from app.extract.reprocess import _document_patch
from app.models import NoticeRevision
from app.qualification import is_metadata, requirements_complete, retire_reviewed_document_candidates
from app.repository import _existing_payload, upsert_notice

SOURCE = next(row for row in json.loads((Path(__file__).parent / "fixtures/official-unranked-current-20261012.json").read_text())
              if row["house_manage_no"] == "2026910255")
DIGEST = SOURCE["document_hash"]


def current_review():
    return parse_official_rules(copy.deepcopy(SOURCE["pages"]), url=SOURCE["document_url"], digest=DIGEST,
        payload={"title": SOURCE["title"], "category": "unsold", "announcement_date": SOURCE["announcement_date"],
                 "official_url": "https://www.applyhome.co.kr/ai/aia/selectAPTRemndrLttotPblancDetailView.do?houseManageNo=" + SOURCE["house_manage_no"]})


def candidate(**changes):
    return {"id": "old-derived-admission", "kind": "unparsed", "verification": "ai_unverified",
            "document_hash": DIGEST, "text": "공고일 현재 부산광역시에 거주하는 무주택세대구성원인 성년자", **changes}


def retire(rules, digest=DIGEST):
    return retire_reviewed_document_candidates(rules, digest=digest, parser_version=PARSER_VERSION)


def test_complete_actual_source_review_retires_only_same_hash_derived_conditions():
    review = current_review()
    assert review["status"] == "complete" and requirements_complete(review["rules"], False)
    removed = [candidate(), candidate(id="old-auto", verification="auto_unverified")]
    retained = [candidate(id="other-source", document_hash="another-document"),
                candidate(id="unidentified", document_hash=None), candidate(id="empty-hash", document_hash=""),
                candidate(id="source-metadata", kind="qualification_context", effect="metadata"),
                candidate(id="actual-official", verification="official", kind="age_min", value=19)]
    before = [*review["rules"], *removed, *retained]
    assert retire(before) == [*review["rules"], *retained]
    assert all(rule in before for rule in removed), "Filtering must not mutate the source snapshot"


@pytest.mark.parametrize("broken", ["partial", "different_hash", "old_parser", "no_admission", "no_coverage",
                                     "missing_evidence", "missing_referenced_fact", "unverified_nested_child",
                                     "review_scope_wrong_hash", "no_review_scope_hash"])
def test_incomplete_or_unbound_review_does_not_erase_unverified_source_interpretation(broken):
    rules = current_review()["rules"]
    coverage = next(rule for rule in rules if rule["kind"] == "condition_coverage")
    if broken == "partial":
        coverage["status"] = "partial"
        coverage["scopes"][0]["complete"] = False
    elif broken == "different_hash":
        coverage["document_hash"] = "different-original"
    elif broken == "old_parser":
        for rule in rules:
            rule["parser_version"] = "official-sections-2026-10-07-v9"
    elif broken == "no_admission":
        rules = [rule for rule in rules if is_metadata(rule)]
    elif broken == "no_coverage":
        rules.remove(coverage)
    elif broken == "missing_evidence":
        coverage["evidence_url"] = ""
    elif broken == "missing_referenced_fact":
        # A public full-source certification must reference the conditions it
        # certifies, even if another structural review format had no such list.
        scope = coverage["scopes"][0]
        actual = [rule["id"] for rule in rules if not is_metadata(rule)
                  and rule.get("effect") not in {"priority", "procedure", "instruction"}]
        scope.update(review_version="generic-admission-2026-10-12-public-v1",
                     completion_basis="current_document_clause_coverage", source_gaps=[],
                     branches=[{"required": True, "status": "verified", "rule_ids": actual}],
                     verified_rule_count=len(actual),
                     topics=[{"required": True, "status": "verified", "rule_ids": actual}])
        rules = [rule for rule in rules if rule.get("id") != actual[0]]
    elif broken == "review_scope_wrong_hash":
        coverage["scopes"][0]["reviewed_document_hash"] = "different-original"
    elif broken == "no_review_scope_hash":
        coverage["scopes"][0].pop("reviewed_document_hash")
    else:
        rule = next(rule for rule in rules if not is_metadata(rule))
        rule.update(kind="all", conditions=[candidate(id="unverified-child")])
    original = [*rules, candidate()]
    assert retire(original) == original


@pytest.mark.parametrize("digest", [None, "", " ", "different-original"])
def test_unknown_or_different_current_document_never_retires_derived_conditions(digest):
    original = [*current_review()["rules"], candidate()]
    assert retire(original, digest=digest) == original


def original_payload():
    return {"source": "cheongyak_home", "external_id": "reviewed-existing-document", "title": SOURCE["title"],
            "category": "unsold", "announcement_date": SOURCE["announcement_date"],
            "official_url": "https://www.applyhome.co.kr/current-notice", "document_hash": DIGEST,
            "rules": [candidate()], "rules_complete": False,
            "events": [{"kind": "general", "start_date": "2026-10-19"}],
            "prices": [{"unit_type": "084.9821A", "price_kind": "sale_max", "amount_krw": 477700000,
                        "verification": "official"}, {"unit_type": "84A", "price_kind": "sale_total", "amount_krw": 477700000,
                        "verification": "ai_unverified", "document_hash": DIGEST}]}


@pytest.mark.asyncio
async def test_successful_pipeline_and_document_patch_retire_stale_candidate_and_preserve_raw_prices(monkeypatch):
    parsed = current_review()
    async def local(url, client, *, payload):
        return {**parsed, "document_url": SOURCE["document_url"], "document_hash": DIGEST,
                "diagnostics": [pipeline.document_diagnostic("decode", "document_read", SOURCE["document_url"], status="ok")]}
    monkeypatch.setattr(pipeline, "extract_local_document", local)
    original = original_payload()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
            httpx.Response(200, text=f'<a href="{SOURCE["document_url"]}">모집공고문 PDF</a>'))) as client:
        enriched = await pipeline.enrich_notice(copy.deepcopy(original), client, known_document_hash=DIGEST, allow_gemini=False)
    assert not any(rule.get("id") == candidate()["id"] for rule in enriched["rules"])
    assert enriched["prices"] == original["prices"]
    patch = _document_patch(original, enriched)
    assert not any(rule.get("id") == candidate()["id"] for rule in patch["rules"])
    assert patch["rules_complete"] and "prices" not in patch and "events" not in patch


def test_persistence_cannot_restore_same_hash_candidate_and_keeps_prices_events_and_revision(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'retirement.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        notice = upsert_notice(session, original_payload())
        session.commit()
        old = copy.deepcopy(_existing_payload(notice))
        assert not notice.rules_complete
        before_revision = session.scalar(select(NoticeRevision).where(NoticeRevision.notice_id == notice.id,
                                                                      NoticeRevision.version == notice.version))
        before_payload = copy.deepcopy(before_revision.payload)
        parsed = current_review()
        updated = upsert_notice(session, _document_patch(old, {**old, "rules": parsed["rules"]}))
        session.commit()
        actual = _existing_payload(updated)
        assert updated.rules_complete and updated.version == 2 and updated.document_hash == DIGEST
        assert not any(rule.get("id") == candidate()["id"] for rule in actual["rules"])
        assert actual["prices"] == old["prices"] and actual["events"] == old["events"]
        assert session.scalar(select(NoticeRevision).where(NoticeRevision.notice_id == notice.id,
                                                         NoticeRevision.version == 1)).payload == before_payload
        assert candidate() in before_payload["rules"], "The prior source revision must preserve its unverified candidate"
        # Later metadata-only source polls preserve that completed review and
        # cannot recreate the superseded candidate from the prior revision.
        polled = upsert_notice(session, {"source": updated.source, "external_id": updated.external_id,
            "rules": [{"kind": "housing_classification", "effect": "metadata", "verification": "official", "housing_kind": "national"}]})
        session.commit()
        assert polled.rules_complete and actual["prices"] == _existing_payload(polled)["prices"]
    engine.dispose()
