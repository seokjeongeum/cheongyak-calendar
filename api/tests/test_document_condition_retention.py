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


def test_generic_partial_review_keeps_an_unanswered_prior_verified_fact_for_same_bytes():
    old = rule("parent_age_min", "노부모부양 특별공급", value=65)
    current = [rule("age_min", value=19, parser_version=PARSER_VERSION),
               coverage({"supply_type": "노부모부양 특별공급", "complete": False,
                         "review_version": "generic-admission-new-version", "reviewed_pages": [1, 2, 3],
                         "completion_basis": "document_structure_reviewed_standard_branch",
                         "topics": [{"topic": "부모 부양 조항", "required": True, "status": "missing"}]})]
    assert old in retain([old], current)


def waiver_coverage(supply="신혼부부 특별공급", *, kind="household_head", **fields):
    scope = {"supply_type": supply, "complete": False, "verified_rule_count": 1,
             "review_version": "generic-admission-future-source", "reviewed_pages": [1, 7],
             "completion_basis": "document_structure_reviewed_standard_branch", "missing_topics": ["미확보 조건"],
             "topics": [{"topic": "해당 유형은 세대주 요건 면제", "status": "not_applicable", "required": False,
                         "waived_rule_kind": kind, "evidence_page": 7, "evidence_text": "세대주 요건: 신혼부부 X"}]}
    return coverage(scope) | {"evidence_url": "https://official.example/future-notice.pdf", **fields}


def test_source_exemption_retires_only_waived_fact_in_partial_review():
    waived = rule("household_head", "신혼부부 특별공급", value=True)
    unanswered = rule("homeless", "신혼부부 특별공급", value=True)
    other_supply = rule("household_head", "노부모부양 특별공급", value=True)
    global_fact = rule("household_head", supply=None, value=True)
    ranked = rule("household_head", "신혼부부 특별공급", purpose="first_rank", value=True)
    fresh = [waiver_coverage()]
    merged = retain([waived, unanswered, other_supply, global_fact, ranked], fresh)
    assert waived not in merged
    assert all(old in merged for old in [unanswered, other_supply, global_fact, ranked])


@pytest.mark.parametrize("change", [{"document_hash": "other-file"}, {"source": "other_collector"},
                                    {"parser_version": OLD_PARSER}, {"evidence_url": ""}])
def test_exemption_without_current_source_provenance_cannot_retire_fact(change):
    old = rule("household_head", "신혼부부 특별공급", value=True)
    assert old in retain([old], [waiver_coverage(**change)])


def test_source_exemption_retires_whole_old_branch_and_keeps_selection_children():
    child = rule("household_head", supply=None, value=True)
    child.pop("supply_type")
    old_branch = rule("all", "신혼부부 특별공급", conditions=[child])
    selection = {**old_branch, "effect": "priority"}
    fresh = [waiver_coverage()]
    assert old_branch not in retain([old_branch], fresh)
    # Selection facts are not reconsidered as admission facts.
    assert retain([selection], fresh) == fresh


@pytest.mark.parametrize("malformed", [{"topics": [None]}, {"topics": [{"required": [], "status": "verified"}]},
                                       {"reviewed_pages": [True]}, {"reviewed_pages": [0]},
                                       {"verified_rule_count": 0}, {"verified_rule_count": True},
                                       {"missing_topics": ["still missing"]}])
def test_malformed_generic_complete_review_cannot_erase_unanswered_fact(malformed):
    old = rule("homeless", value=True)
    scope = {"supply_type": "일반공급", "complete": True, "verified_rule_count": 1,
             "review_version": "generic-admission-new-source", "reviewed_pages": [1], "missing_topics": [],
             "completion_basis": "document_structure_reviewed_standard_branch", "topics": [], **malformed}
    fresh = [rule("age_min", value=19, parser_version=PARSER_VERSION),
             coverage(scope) | {"status": "complete", "offered_supply_types": ["일반공급"]}]
    assert old in retain([old], fresh)


def test_malformed_scope_is_not_filtered_out_before_whole_review_check():
    old = rule("parent_age_min", "노부모부양 특별공급", value=65)
    valid_scope = {"supply_type": "일반공급", "complete": True, "verified_rule_count": 1,
                   "review_version": "generic-admission-new-source", "reviewed_pages": [1], "missing_topics": [],
                   "completion_basis": "document_structure_reviewed_standard_branch", "topics": []}
    fresh = [rule("age_min", value=19, parser_version=PARSER_VERSION),
             coverage(valid_scope, None) | {"status": "complete", "offered_supply_types": ["일반공급", "노부모부양 특별공급"]}]
    assert old in retain([old], fresh)


def test_generic_complete_coverage_alone_cannot_replace_prior_admission_proof():
    old = rule("homeless", value=True)
    scope = {"supply_type": "일반공급", "complete": True, "verified_rule_count": 1,
             "review_version": "generic-admission-new-source", "reviewed_pages": [1], "missing_topics": [],
             "completion_basis": "document_structure_reviewed_standard_branch"}
    fresh = [coverage(scope) | {"status": "complete", "offered_supply_types": ["일반공급"],
                               "evidence_url": "https://official.example/current-document.pdf"}]
    assert old in retain([old], fresh)


def test_unparsed_exception_is_not_a_replacement_for_an_unmodelled_known_branch():
    old = rule("tax_years_min", "생애최초 특별공급", value=5,
               exceptions=[rule("unparsed", "생애최초 특별공급", label="세액공제 인정 범위")])
    fresh = [rule("unparsed", "생애최초 특별공급", parser_version=PARSER_VERSION,
                  label="다른 미확보 신청 조항")]
    assert old in retain([old], fresh)


def replacement_fact(**fields):
    return rule("first_home_tax_activity", "생애최초 특별공급", value=True, parser_version=PARSER_VERSION,
                supersedes_rule_kinds=["tax_years_min"], evidence_page=17,
                evidence_url="https://official.example/future-notice.pdf", evidence_text="5년 이상 소득세 및 최근 1년 납부 인정", **fields)


def test_current_source_model_explicitly_supersedes_only_the_scoped_older_kind():
    old = rule("tax_years_min", "생애최초 특별공급", value=5)
    other = rule("tax_years_min", "다른 공급", value=5)
    global_fact = rule("tax_years_min", supply=None, value=5)
    unanswered = rule("homeless", "생애최초 특별공급", value=True)
    new = replacement_fact()
    merged = retain([old, other, global_fact, unanswered], [new])
    assert old not in merged and new in merged
    assert all(item in merged for item in (other, global_fact, unanswered))


@pytest.mark.parametrize("change", [{"document_hash": "other-file"}, {"source": "other_collector"},
                                    {"evidence_page": 0}, {"evidence_text": ""}, {"supersedes_rule_kinds": "tax_years_min"}])
def test_replacement_descriptor_requires_real_current_source_evidence(change):
    old = rule("tax_years_min", "생애최초 특별공급", value=5)
    assert old in retain([old], [replacement_fact() | change])


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
