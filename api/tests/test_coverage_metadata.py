"""Malformed coverage data cannot certify or discard source conditions."""
import pytest

from app.qualification import generic_admission_coverage_complete, requirements_complete


def review(scope):
    return {"kind": "condition_coverage", "effect": "metadata", "verification": "official",
            "source": "official_document_parser", "status": "complete", "document_hash": "new-document",
            "evidence_url": "https://official.example/new.pdf", "offered_supply_types": ["일반공급"], "scopes": [scope]}


def generic_scope(**fields):
    return {"supply_type": "일반공급", "complete": True, "verified_rule_count": 1,
            "review_version": "generic-admission-future", "reviewed_pages": [1, 19], "missing_topics": [],
            "completion_basis": "document_structure_reviewed_standard_branch", **fields}


@pytest.mark.parametrize("scope", [None, [],
    generic_scope(complete=1), generic_scope(topics=[None]),
    generic_scope(topics=[{"required": [], "status": "verified"}]),
    generic_scope(topics=[{"required": True, "status": "missing"}]),
    generic_scope(reviewed_pages=[]), generic_scope(reviewed_pages=[True]), generic_scope(reviewed_pages=[0]),
    generic_scope(verified_rule_count=True), generic_scope(verified_rule_count=0),
    generic_scope(missing_topics=None), generic_scope(missing_topics=["未검토 조건"]),
    generic_scope(review_version={}), generic_scope(supply_types=5),
])
def test_malformed_scope_is_incomplete_without_raising(scope):
    metadata = review(scope)
    condition = {"kind": "age_min", "value": 19, "verification": "official"}
    assert requirements_complete([condition, metadata], declared=True) is False
    assert generic_admission_coverage_complete(metadata) is False


def test_source_review_without_topic_list_can_complete_office_or_unranked_scope():
    metadata = review(generic_scope())
    assert generic_admission_coverage_complete(metadata)
    assert requirements_complete([{"kind": "age_min", "value": 19, "verification": "official"}, metadata], declared=False)


def test_legacy_sparse_scope_still_certifies_its_verified_conditions():
    metadata = review({"supply_type": "일반공급", "complete": True})
    assert requirements_complete([{"kind": "age_min", "value": 19, "verification": "official"}, metadata], declared=False)
    assert not generic_admission_coverage_complete(metadata)


def test_one_unit_or_missing_offered_supply_is_not_a_whole_source_review():
    assert not generic_admission_coverage_complete(review(generic_scope(unit_type="084A")))
    metadata = review(generic_scope())
    metadata["offered_supply_types"].append("노부모부양 특별공급")
    assert not generic_admission_coverage_complete(metadata)


def test_nonlist_coverage_scopes_are_incomplete():
    metadata = review(generic_scope())
    metadata["scopes"] = {"complete": True}
    assert not requirements_complete([{"kind": "age_min", "verification": "official"}, metadata], declared=True)


def public_scope(**fields):
    return generic_scope(review_version="generic-admission-2026-10-12-public-v1",
                         completion_basis="current_document_clause_coverage",
                         reviewed_document_hash="new-document", source_gaps=[],
                         topics=[{"topic": "age", "required": True, "status": "verified", "rule_ids": ["adult-age"]}],
                         branches=[{"branch_id": "adult", "required": True, "status": "verified"}], **fields)


def test_public_clause_coverage_requires_current_hash_and_reviewed_branches():
    condition = {"id": "adult-age", "kind": "age_min", "value": 19, "verification": "official", "document_hash": "new-document"}
    metadata = review(public_scope())
    assert requirements_complete([condition, metadata], declared=False)
    assert generic_admission_coverage_complete(metadata)
    for changed in [
        {"completion_basis": "document_structure_reviewed_standard_branch"},
        {"reviewed_document_hash": "other-bytes"}, {"source_gaps": ["unknown clause"]},
        {"branches": []}, {"branches": [{"required": True, "status": "missing"}]},
        {"branches": [{"required": 0, "status": "verified"}]},
        {"review_version": "generic-admission-future-public"}, {"review_version": None},
    ]:
        invalid = review({**public_scope(), **changed})
        assert not requirements_complete([condition, invalid], declared=True)
        assert not generic_admission_coverage_complete(invalid)
    assert not requirements_complete([{**condition, "id": "other"}, metadata], declared=True)
    assert not requirements_complete([{**condition, "document_hash": "older"}, metadata], declared=True)
