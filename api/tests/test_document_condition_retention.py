"""Partial reparses retain unanswered same-byte facts without reviving errors."""
import json
from pathlib import Path

import httpx
import pytest

from app.extract import pipeline
from app.extract.official_rules import PARSER_VERSION, parse_official_rules

OLD_PARSER = "official-sections-2026-10-07-v9"


def rule(kind, supply="일반공급", **fields):
    return {"kind": kind, "supply_type": supply, "effect": "eligibility", "verification": "official",
            "source": "official_document_parser", "document_hash": "same-file", "parser_version": OLD_PARSER, **fields}


def coverage(*scopes):
    return rule("condition_coverage", effect="metadata", parser_version=PARSER_VERSION,
                scopes=list(scopes), status="partial")


def retain(previous, incoming):
    return pipeline._retain_same_hash_conditions(previous, incoming, "same-file", {"category": "apt", "title": "민영 공고"})


def test_partial_parse_retains_unanswered_scoped_facts_and_original_parser_provenance():
    old = [rule("homeless", "신혼부부 특별공급", value=True),
           rule("parent_age_min", "노부모부양 특별공급", value=65),
           rule("deposit_min_krw", purpose="first_rank", value=3000000)]
    current = [rule("age_min", value=19, parser_version=PARSER_VERSION),
               coverage({"supply_type": "일반공급", "complete": False, "missing_topics": ["신청 제한 적용 대상"]})]
    merged = retain(old, current)
    assert all(previous in merged for previous in old)
    assert all(previous["parser_version"] == OLD_PARSER for previous in old)
    assert retain(merged, current) == merged


def test_replaced_nested_leaf_retires_old_containing_branch_and_normalizes_eligibility_purpose():
    old = rule("any", conditions=[rule("age_min", value=18), rule("household_head", value=True)])
    previous_rank = rule("private_rank_months", "신혼부부 특별공급", value=6, purpose="eligibility")
    current = [rule("any", label="성년 또는 법정 미성년 세대주", parser_version=PARSER_VERSION,
                    conditions=[rule("age_min", value=19, parser_version=PARSER_VERSION)]),
               rule("private_rank_months", "신혼부부 특별공급", value=12, parser_version=PARSER_VERSION)]
    merged = retain([old, previous_rank], current)
    assert old not in merged and previous_rank not in merged
    assert merged == current


def test_complete_admission_scope_retires_older_scope_without_losing_other_supply_or_rank_facts():
    old_general = rule("household_head", value=True)
    old_other = rule("household_head", "노부모부양 특별공급", value=True)
    old_rank = rule("deposit_min_krw", purpose="first_rank", value=3000000)
    current = [rule("age_min", value=19, parser_version=PARSER_VERSION),
               coverage({"supply_type": "일반공급", "complete": True, "missing_topics": []})]
    merged = retain([old_general, old_other, old_rank], current)
    assert old_general not in merged and old_other in merged and old_rank in merged


def test_other_hash_and_incompatible_parser_facts_are_not_revived():
    wrong_hash = rule("homeless", value=True, document_hash="other-file")
    obsolete = rule("household_head", value=True, parser_version="obsolete-parser")
    assert retain([wrong_hash, obsolete], []) == []


def test_selection_or_procedure_children_do_not_replace_admission_requirements():
    old = rule("homeless", "신혼부부 특별공급", value=True)
    for effect in ("priority", "procedure", "instruction"):
        selection = rule("any", "신혼부부 특별공급", effect=effect, parser_version=PARSER_VERSION,
                         conditions=[rule("homeless", "신혼부부 특별공급", value=False, parser_version=PARSER_VERSION)])
        assert old in retain([old], [selection])


def test_exact_whole_source_hangang_review_replaces_unmatched_legacy_admission_set():
    rows = json.loads((Path(__file__).parent / "fixtures/current-private-v5.json").read_text())
    source = next(row for row in rows if row["external_id"] == "2026000468")
    parsed = parse_official_rules(source["pages"], url=source["document_url"],
                                  digest=source["document_hash"], payload=source["payload"])
    old = rule("household_head", "신혼부부 특별공급", value=True, document_hash=source["document_hash"])
    merged = pipeline._retain_same_hash_conditions([old], parsed["rules"], source["document_hash"], source["payload"])
    assert merged == parsed["rules"] and old not in merged
    reviewed = next(item for item in merged if item["kind"] == "condition_coverage")
    assert any(scope.get("review_version") for scope in reviewed["scopes"])


@pytest.mark.asyncio
async def test_same_hash_partial_enrichment_keeps_raw_unmatched_special_requirement(monkeypatch):
    old = rule("parent_age_min", "노부모부양 특별공급", value=65)
    current = rule("age_min", value=19, parser_version=PARSER_VERSION)
    payload = {"official_url": "https://www.applyhome.co.kr/notice", "category": "apt",
               "document_hash": "same-file", "rules": [old]}

    async def extract(url, client, *, payload):
        return {"document_hash": "same-file", "document_url": url, "rules": [current], "status": "partial",
                "diagnostics": [pipeline.document_diagnostic("decode", "document_read", url, status="ok")]}

    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text='<a href="/notice.pdf">모집공고문</a>'))) as client:
        result = await pipeline.enrich_notice(payload, client, known_document_hash="same-file", allow_gemini=False)
    assert old in result["rules"] and current in result["rules"]
    assert old["parser_version"] == OLD_PARSER
