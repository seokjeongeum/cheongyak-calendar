"""Compatible source reviews remain effective after an unrelated parser bump."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from app.extract.official_rules import PARSER_VERSION, parse_official_rules
from app.repository import notice_public, upsert_notice
from test_repository_api import classification, db, document_rule, example_notice

V15 = "official-sections-2026-10-11-v15"
V13 = "official-sections-2026-10-09-v13"
V8 = "official-sections-2026-10-07-v8"


def parsed_version(value, version):
    if isinstance(value, list):
        return [parsed_version(item, version) for item in value]
    if isinstance(value, dict):
        return {key: version if key == "parser_version" and item == PARSER_VERSION else parsed_version(item, version)
                for key, item in value.items()}
    return value


def stored_pair(db, current, prior, *, digest="reviewed-file"):
    raw = example_notice(external_id="LATEST-REVIEW")
    raw.update(document_hash=digest, rules=[classification(), *current])
    canonical = upsert_notice(db, raw)
    duplicate = upsert_notice(db, {**raw, "source": "myhome", "external_id": "PRIOR-REVIEW",
                                  "rules": [classification(), *prior]})
    db.commit()
    assert duplicate.duplicate_of_id == canonical.id
    return canonical, duplicate


def fact(kind, *, version=V15, **fields):
    return document_rule(kind, version=version, supply_type="생애최초 특별공급", **fields)


def tax_model(**fields):
    return fact("first_home_tax_activity", value=True, supersedes_rule_kinds=["tax_years_min"],
                evidence_page=17, evidence_url="https://official.example/current.pdf",
                evidence_text="5년 이상 소득세 납부 및 최근 1년 납부 인정", **fields)


def partial(version=PARSER_VERSION):
    return document_rule("condition_coverage", version=version, effect="metadata", status="partial",
                         scopes=[{"supply_type": "일반공급", "complete": False, "missing_topics": ["미확보 조항"]}])


@pytest.mark.parametrize("supplement", ["none", "new_area_metadata", "new_partial_age"])
def test_actual_v15_hangang_review_does_not_revive_same_hash_legacy_tax(db, supplement):
    fixtures = Path(__file__).parent / "fixtures"
    source = next(row for row in json.loads((fixtures / "current-private-v5.json").read_text())
                  if row["external_id"] == "2026000468")
    prior = json.loads((fixtures / "hangang-prior-generic-v8.json").read_text())
    assert source["document_hash"] == prior["document_hash"]
    parsed = parse_official_rules(source["pages"], url=source["document_url"],
                                  digest=source["document_hash"], payload=source["payload"])
    reviewed = parsed_version(parsed["rules"], V15)
    current = deepcopy(reviewed)
    if supplement == "new_area_metadata":
        current.append(next(rule for rule in parsed["rules"] if rule["kind"] == "unit_exclusive_areas"))
    elif supplement == "new_partial_age":
        current.extend([document_rule("age_min", version=PARSER_VERSION, digest=source["document_hash"],
                                      supply_type="일반공급", value=19),
                        {**partial(), "document_hash": source["document_hash"]}])
    raw = {**source["payload"], "source": "cheongyak_home", "external_id": source["external_id"],
           "provider": "한국부동산원", "document_hash": source["document_hash"], "rules": [classification(), *current]}
    canonical = upsert_notice(db, raw)
    duplicate = upsert_notice(db, {**raw, "source": "myhome", "external_id": "OLDER-OFFICIAL-COPY",
                                  "rules": [classification(), *prior["rules"]]})
    db.commit()
    assert duplicate.duplicate_of_id == canonical.id
    for detail in (False, True):
        public = notice_public([canonical, duplicate], detail=detail)
        assert not any(rule["kind"] == "tax_years_min" for rule in public.rules)
        assert any(rule["kind"] == "first_home_tax_activity" and rule["parser_version"] == V15
                   for rule in public.rules)
        assert public.rules_complete is False
        assert len(public.prices) == len(canonical.prices)
    assert duplicate.rules == [classification(), *prior["rules"]]
    assert duplicate.revisions[0].payload["rules"] == duplicate.rules


def test_current_or_newest_compatible_scoped_review_wins_without_erasing_other_scopes(db):
    oldest = fact("private_rank_months", version=V8, value=6)
    compatible = fact("private_rank_months", value=12)
    newest = {**compatible, "parser_version": PARSER_VERSION, "value": 24}
    unrelated = {**oldest, "supply_type": "신혼부부 특별공급"}
    canonical, duplicate = stored_pair(db, [compatible], [oldest, unrelated])
    rules = notice_public([canonical, duplicate]).rules
    assert compatible in rules and oldest not in rules and unrelated in rules
    upsert_notice(db, {"source": canonical.source, "external_id": canonical.external_id,
                       "rules": [classification(), compatible, newest], "replace_rules": True})
    db.commit()
    rules = notice_public([canonical, duplicate]).rules
    assert newest in rules and compatible not in rules and unrelated in rules


def test_v15_complete_review_retires_unmatched_older_admission_only_for_exact_bytes(db):
    age = document_rule("age_min", version=V15, value=19, supply_type="일반공급")
    coverage = document_rule("condition_coverage", version=V15, effect="metadata", status="complete",
        evidence_url="https://official.example/current.pdf", offered_supply_types=["일반공급"],
        scopes=[{"supply_type": "일반공급", "complete": True, "verified_rule_count": 1,
                 "review_version": "generic-admission-future-source", "reviewed_pages": [1], "topics": [],
                 "completion_basis": "document_structure_reviewed_standard_branch", "missing_topics": []}])
    old = document_rule("household_head", version=V8, value=True, supply_type="일반공급")
    canonical, duplicate = stored_pair(db, [age, coverage], [old])
    assert old not in notice_public([canonical, duplicate]).rules
    duplicate.document_hash = "separate-provider-file"
    duplicate.rules = [{**old, "document_hash": duplicate.document_hash}]
    db.commit()
    assert duplicate.rules[0] in notice_public([canonical, duplicate]).rules


def test_new_partial_age_review_keeps_prior_tax_supersession_and_unanswered_fact(db):
    old_tax = fact("tax_years_min", version=V8, value=5)
    other_supply = {**old_tax, "supply_type": "다른 공급"}
    unanswered = fact("additional_official_tax_treatment", version=V8, value=True)
    model = tax_model()
    current = [document_rule("age_min", version=PARSER_VERSION, value=19, supply_type="일반공급"),
               partial(), model]
    canonical, duplicate = stored_pair(db, current, [old_tax, other_supply, unanswered])
    public = notice_public([canonical, duplicate])
    assert old_tax not in public.rules and model in public.rules
    assert other_supply in public.rules and unanswered in public.rules
    assert public.rules_complete is False


def test_older_tax_descriptor_cannot_remove_newer_relevant_requirement(db):
    old_tax = fact("tax_years_min", version=V8, value=5)
    current_tax = fact("tax_years_min", version=PARSER_VERSION, value=6)
    model = tax_model()
    canonical, duplicate = stored_pair(db, [model, current_tax, partial()], [old_tax])
    rules = notice_public([canonical, duplicate]).rules
    assert current_tax in rules and old_tax not in rules


def source_waiver():
    return document_rule("condition_coverage", version=V15, effect="metadata", status="partial",
        evidence_url="https://official.example/current.pdf", scopes=[{
            "supply_type": "신혼부부 특별공급", "complete": False, "verified_rule_count": 1,
            "review_version": "generic-admission-future-source", "reviewed_pages": [1, 7],
            "completion_basis": "document_structure_reviewed_standard_branch", "missing_topics": ["미확보 조항"],
            "topics": [{"status": "not_applicable", "required": False, "waived_rule_kind": "household_head",
                        "evidence_page": 7, "evidence_text": "신혼부부 특별공급 세대주 요건 면제"}]}])


def test_prior_waiver_survives_unrelated_partial_review_but_not_newer_head_requirement(db):
    old = document_rule("household_head", version=V8, value=True, supply_type="신혼부부 특별공급")
    unanswered = {**old, "kind": "homeless"}
    age = document_rule("age_min", version=PARSER_VERSION, value=19, supply_type="일반공급")
    waiver = source_waiver()
    canonical, duplicate = stored_pair(db, [age, partial(), waiver], [old, unanswered])
    rules = notice_public([canonical, duplicate]).rules
    assert old not in rules and unanswered in rules
    current_head = {**old, "parser_version": PARSER_VERSION}
    upsert_notice(db, {"source": canonical.source, "external_id": canonical.external_id,
                       "rules": [classification(), age, partial(), waiver, current_head], "replace_rules": True})
    db.commit()
    assert current_head in notice_public([canonical, duplicate]).rules


@pytest.mark.parametrize("change", [{"document_hash": "changed-file"},
                                    {"parser_version": "obsolete-parser"}, {"verification": "ai_unverified"},
                                    {"evidence_text": ""}])
def test_incompatible_or_unbound_tax_descriptor_never_retires_reviewed_fact(db, change):
    old_tax = fact("tax_years_min", version=V8, value=5)
    canonical, duplicate = stored_pair(db, [tax_model() | change, partial()], [old_tax])
    assert old_tax in notice_public([canonical, duplicate]).rules


def test_compatible_diagnostics_choose_newest_review_and_never_certify_admission(db):
    admission = fact("homeless", version=V13, value=True)
    failed = document_rule("document_diagnostics", version=V13, effect="metadata", status="unreadable",
        diagnostics=[{"stage": "download", "code": "document_download_failed", "status": "error"}])
    resolved = {**failed, "parser_version": V15, "status": "partial",
                "diagnostics": [{"stage": "download", "code": "document_download_failed", "status": "resolved"}]}
    canonical, duplicate = stored_pair(db, [admission, resolved], [failed])
    duplicate.updated_at = datetime(2027, 1, 1, tzinfo=timezone.utc)
    db.commit()
    public = notice_public([canonical, duplicate])
    assert resolved in public.rules and failed not in public.rules and admission in public.rules
    assert public.rules_complete is False


def test_newer_relevant_model_without_descriptor_does_not_reuse_prior_supersession(db):
    old_tax = fact("tax_years_min", version=V8, value=5)
    prior_model = tax_model()
    new_model = {**prior_model, "parser_version": PARSER_VERSION, "supersedes_rule_kinds": []}
    canonical, duplicate = stored_pair(db, [prior_model, new_model, partial()], [old_tax])
    rules = notice_public([canonical, duplicate]).rules
    assert new_model in rules and prior_model not in rules and old_tax in rules


def test_compatible_dated_review_order_survives_future_version_number_reset(db, monkeypatch):
    from app.extract import official_rules

    future = "official-sections-2026-10-12-v2"
    usable = official_rules.parser_version_usable
    monkeypatch.setattr(official_rules, "parser_version_usable",
                        lambda rule, **kwargs: rule.get("parser_version") == future or usable(rule, **kwargs))
    prior = fact("age_min", value=19)
    fresh = {**prior, "parser_version": future, "value": 20}
    canonical, duplicate = stored_pair(db, [fresh], [prior])
    rules = notice_public([canonical, duplicate]).rules
    assert fresh in rules and prior not in rules
