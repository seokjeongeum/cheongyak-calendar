import copy
import json
from pathlib import Path

import pytest

from app.extract.official_rules import PARSER_VERSION, application_method, parse_official_rules
from app.extract.unranked_rules import ADULT_LAW_URL
from app.qualification import public_application_method, public_classification, public_rank_applicability
from test_repository_api import client, db, example_notice, qualification_context
from app.repository import upsert_notice
from app.extract.reprocess import _document_patch


FIXTURES = json.loads((Path(__file__).parent / "fixtures/official-rules-v4-unranked.json").read_text())


def fixture(number):
    return copy.deepcopy(next(f for f in FIXTURES if f["house_manage_no"] == number))


def parse(number, **kwargs):
    f = fixture(number)
    return parse_official_rules(f["pages"], url=f["document_url"], digest=f["document_hash"], **kwargs)


def walk(rules):
    for rule in rules:
        yield rule
        yield from walk(rule.get("conditions", []))


@pytest.mark.parametrize("number,method,current,original,region", [
    ("2026910249", "unranked_after", "2026-10-01", "2026-07-31", "36"),
    ("2026910250", "unranked_after", "2026-10-01", "2021-07-22", "11"),
    ("2026930040", "cancelled_resupply", "2026-09-23", "2024-05-31", "11"),
])
def test_reviewed_nonranked_offers_have_actual_complete_conditions_at_current_cutoff(number, method, current, original, region):
    result = parse(number)
    assert result["status"] == "complete"
    assert result["offered_supply_types"] == ["일반공급"]
    rules = result["rules"]
    assert public_application_method(rules)[0] == method
    assert public_application_method(rules)[1].criterion_date.isoformat() == current
    rank = public_rank_applicability(rules)
    assert rank.status == "not_applicable" and rank.account_required is False
    kind, _, context = public_classification(rules)
    assert kind == "private"
    assert context.original_announcement_date.isoformat() == original
    assert context.application_criterion_date.isoformat() == current
    assert context.application_announcement_date.isoformat() == current
    assert next(r for r in rules if r["kind"] == "residence_region")["region_code"] == region
    assert next(r for r in rules if r["kind"] == "homeless")["value"] is True
    assert not any(r.get("purpose") == "first_rank" or r["kind"] == "rank_requirements" for r in rules)
    coverage = next(r for r in rules if r["kind"] == "condition_coverage")
    assert coverage["completion_basis"] == "document_hash_review"
    assert coverage["scopes"][0]["complete"] is True
    for rule in walk(rules):
        assert rule["criterion_date"] == current
        assert rule["document_hash"] == fixture(number)["document_hash"]
        if rule.get("verification_basis") == "official_law_review":
            assert rule["evidence_page"] is None
            assert rule["evidence_section"] == "제26조제5항"
            assert rule["applied_document_page"] in [p["page"] for p in fixture(number)["pages"]]
        else:
            assert rule["evidence_page"] in [p["page"] for p in fixture(number)["pages"]]
        assert rule["evidence_text"] and rule["verification"] == "official"
        assert rule["parser_version"] == PARSER_VERSION


def test_head_requirement_belongs_to_cancelled_resupply_and_does_not_leak_to_after_supply():
    assert next(r for r in parse("2026930040")["rules"] if r["kind"] == "household_head")["value"] is True
    for number in ("2026910249", "2026910250"):
        assert not any(r["kind"] == "household_head" for r in walk(parse(number)["rules"]))


def test_project_history_is_keyed_to_original_project_and_contract_includes_additional_residents():
    for number, project in (("2026910249", "2026000323"), ("2026910250", "2021000515")):
        rules = [r for r in parse(number)["rules"] if r.get("restriction", "").startswith("prior_project_")]
        assert {r["restriction"] for r in rules} == {"prior_project_winner", "prior_project_contract"}
        assert all(r["project_id"] == project and r["scope"] == "applicant" and r["value"] is False for r in rules)
        assert next(r for r in rules if r["restriction"] == "prior_project_contract")["include_additional_resident"] is True


def test_rewinning_and_sanctioned_application_restrictions_keep_their_actual_subjects():
    sejong = parse("2026910249")["rules"]
    assert not any(r.get("restriction") == "rewinning_restriction_active" for r in sejong)
    sillim = next(r for r in parse("2026910250")["rules"] if r.get("restriction") == "rewinning_restriction_active")
    gang = next(r for r in parse("2026930040")["rules"] if r.get("restriction") == "rewinning_restriction_active")
    assert sillim["scope"] == "household" and gang["scope"] == "applicant_spouse"
    for number in ("2026910249", "2026910250", "2026930040"):
        rule = next(r for r in parse(number)["rules"] if r.get("restriction") == "resale_restriction_active")
        assert rule["scope"] == "applicant" and rule["value"] is False
        assert "교란" in rule["evidence_text"]


def test_current_official_adult_rule_and_underage_exception_are_an_alternative_not_blanket_failure():
    for number in ("2026910249", "2026910250"):
        adult = next(r for r in parse(number)["rules"] if r["kind"] == "any")
        assert adult["evidence_url"] == ADULT_LAW_URL
        assert adult["verification_basis"] == "official_law_review"
        assert adult["law_effective_date"] == "2026-06-15"
        assert [r["kind"] for r in adult["conditions"]] == ["age_min", "unparsed"]
        assert adult["conditions"][0]["value"] == 19
    gang = next(r for r in parse("2026930040")["rules"] if r["kind"] == "any")
    assert gang["conditions"][1]["kind"] == "all"
    assert gang["conditions"][1]["conditions"][0]["kind"] == "household_head"
    assert "자녀양육" in gang["evidence_text"] and "형제자매부양" in gang["evidence_text"]


def test_overseas_and_foreigner_conditions_are_retained_after_nonranked_classification():
    for number in ("2026910249", "2026910250", "2026930040"):
        rules = parse(number)["rules"]
        overseas = next(r for r in rules if r["kind"] == "overseas_residence")
        assert overseas["max_continuous_days"] == 90 and overseas["livelihood_exception"] is True
        assert "7일" in overseas["evidence_text"] and "생업" in overseas["evidence_text"]
        assert next(r for r in rules if r["kind"] == "citizenship")["allowed_values"] == ["korean"]


def test_changed_hash_cannot_reuse_complete_review_or_project_restrictions():
    f = fixture("2026910249")
    result = parse_official_rules(f["pages"], url=f["document_url"], digest="corrected-document", payload={"category": "unsold"})
    assert result["status"] == "partial"
    assert any(r["kind"] == "residence_region" for r in result["rules"])
    assert not any(r["kind"] == "application_restriction" for r in result["rules"])
    assert next(r for r in result["rules"] if r["kind"] == "condition_coverage")["scopes"][0]["complete"] is False


def test_current_cutoff_is_not_replaced_by_old_project_metadata_and_conflicting_current_date_blocks_parsing():
    old = {"rules": [{"kind": "qualification_context", "verification": "official", "value": {"original_announcement_date": "2026-07-31"}}], "announcement_date": "2026-10-01"}
    assert parse("2026910249", payload=old)["status"] == "complete"
    old["announcement_date"] = "2026-09-01"
    assert parse("2026910249", payload=old)["status"] == "unsupported"


def test_unmatched_restriction_clause_prevents_complete_scope_even_when_other_facts_are_available():
    f = fixture("2026910250")
    for page in f["pages"]:
        page["text"] = page["text"].replace("과거 재당첨 제한 대상 주택에 당첨되어 현재 그 기간 중에 있는 분 및 그 세대원", "별도 정정된 제한 항목")
    result = parse_official_rules(f["pages"], url=f["document_url"], digest=f["document_hash"])
    assert result["status"] == "partial"
    assert any(r["kind"] == "homeless" for r in result["rules"])


def test_document_heading_not_remainder_operation_selects_method_and_never_reuses_original_cutoff():
    pages = [{"page": 1, "text": "민영주택 임의공급 입주자모집공고\n본 임의공급 입주자모집공고일은 2026.10.01.\n본 주택의 최초 입주자모집공고일은 2020.01.01.\n청약통장 가입여부와 무관하게 신청가능"}]
    result = parse_official_rules(pages, url="https://www.applyhome.co.kr/public.pdf", digest="optional", payload={"category": "unsold"})
    assert public_application_method(result["rules"])[0] == "optional_supply"
    assert all(r["criterion_date"] == "2026-10-01" for r in result["rules"])
    assert result["status"] == "partial"
    assert application_method([{"page": 1, "text": "아파트 입주자모집공고\n미계약 잔여물량은 선착순 수의계약 예정"}])[0] == "unknown"


def test_list_detail_add_method_and_evidence_without_mutating_stored_records(db, client):
    f = fixture("2026910249")
    raw = example_notice(external_id=f["house_manage_no"])
    raw.update(category="unsold", title="세종 우미 린 무순위", announcement_date=f["announcement_date"], document_hash=f["document_hash"], rules=parse(f["house_manage_no"])["rules"])
    notice = upsert_notice(db, raw); db.commit()
    before = (notice.version, notice.content_hash, len(notice.revisions), len(notice.prices))
    for value in (client.get("/api/notices").json()["items"][0], client.get(f"/api/notices/{notice.id}").json()):
        assert value["application_method"] == "unranked_after"
        assert value["application_method_evidence"]["document_hash"] == f["document_hash"]
        assert value["application_method_evidence"]["criterion_date"] == "2026-10-01"
        assert value["qualification_context"]["original_announcement_date"] == "2026-07-31"
        assert value["qualification_context"]["application_criterion_date"] == "2026-10-01"
    assert before == (notice.version, notice.content_hash, len(notice.revisions), len(notice.prices))
    assert public_application_method([{"kind": "application_method", "value": "unranked_after", "verification": "ai_unverified"}]) == ("unknown", None)


@pytest.mark.parametrize("category,title,keep", [("apt", "기존 아파트", True), ("officetel", "기존 오피스텔", True),
                                               ("unsold", "무순위 사후", False), ("optional_supply", "임의공급", False),
                                               ("apt", "계약취소 주택 재공급", False)])
def test_v3_ordinary_conditions_survive_gradual_rollout_but_nonranked_old_interpretation_does_not(db, client, category, title, keep):
    old = {"kind": "private_rank_months", "value": 6, "purpose": "first_rank", "verification": "official", "source": "official_document_parser",
           "parser_version": "official-sections-2026-10-04-v3", "document_hash": "same-file"}
    raw = example_notice(); raw.update(category=category, title=title, rules=[old], document_hash="same-file")
    notice = upsert_notice(db, raw); db.commit()
    public = client.get(f"/api/notices/{notice.id}").json()
    assert (old in public["rules"]) is keep
    assert (old in _document_patch(raw, raw)["rules"]) is keep
    assert old in notice.rules  # Projection retains archived raw facts.


def test_reprocess_preserves_current_application_cutoff_separately_from_old_project_date():
    raw = example_notice()
    raw["rules"] = [{"kind": "qualification_context", "verification": "official", "source": "official_api",
                     "value": {"speculation_zone": True, "original_announcement_date": "2026-10-01"}}]
    f = fixture("2026910249")
    parsed = parse(f["house_manage_no"])
    patch = _document_patch(raw, {**raw, "rules": parsed["rules"], "document_hash": f["document_hash"]})
    context = next(r for r in patch["rules"] if r["kind"] == "qualification_context" and r["source"] == "official_document_parser")["value"]
    assert context == {"speculation_zone": True, "original_announcement_date": "2026-07-31",
                       "application_announcement_date": "2026-10-01", "application_criterion_date": "2026-10-01"}


@pytest.mark.parametrize("number", ["2026910249", "2026910250", "2026930040"])
def test_routine_feed_recollection_preserves_reviewed_nonranked_metadata_and_current_cutoff(db, client, number):
    f = fixture(number)
    raw = example_notice(external_id=number)
    raw.update(category="unsold", title=number, announcement_date=f["announcement_date"], document_hash=f["document_hash"], rules=parse(number)["rules"])
    notice = upsert_notice(db, raw); db.commit()
    original = client.get(f"/api/notices/{notice.id}").json()
    original_conditions = [r for r in original["rules"] if r.get("effect") != "metadata"]
    feed = {"source": raw["source"], "external_id": number, "announcement_date": f["announcement_date"],
            "rules": [{"kind": "housing_classification", "effect": "metadata", "housing_kind": "unknown", "verification": "unknown", "source": "cheongyak_home"},
                      qualification_context(original_announcement_date=f["announcement_date"], speculation_zone=False),
                      {"kind": "rank_applicability", "effect": "metadata", "status": "not_applicable", "account_required": None,
                       "verification": "official", "source": "cheongyak_home"}]}
    upsert_notice(db, feed); db.commit()
    for endpoint in ("/api/notices", f"/api/notices/{notice.id}"):
        response = client.get(endpoint).json(); current = response["items"][0] if "items" in response else response
        assert current["housing_kind"] == "private"
        assert current["application_method"] == original["application_method"]
        assert current["rank_applicability"]["account_required"] is False
        assert current["rank_applicability"]["document_hash"] == f["document_hash"]
        assert current["qualification_context"]["application_criterion_date"] == f["announcement_date"]
        assert current["qualification_context"]["original_announcement_date"] == original["qualification_context"]["original_announcement_date"]
        assert current["qualification_context"]["speculation_zone"] is False
        assert [r for r in current["rules"] if r.get("effect") != "metadata"] == original_conditions
        assert next(r for r in current["rules"] if r["kind"] == "condition_coverage")["scopes"][0]["complete"] is True
    # A repeat poll is idempotent, and a real URL/hash change still retires all
    # old document conditions and document-specific metadata together.
    version = notice.version
    assert upsert_notice(db, feed).version == version
    upsert_notice(db, {**feed, "document_hash": "corrected-hash"}); db.commit()
    corrected = client.get(f"/api/notices/{notice.id}").json()
    assert corrected["housing_kind"] == "unknown"
    assert corrected["qualification_context"]["application_criterion_date"] is None
    assert not any(r.get("source") == "official_document_parser" for r in corrected["rules"])
