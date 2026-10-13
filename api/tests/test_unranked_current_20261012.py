"""Current nonranked geography and waivers are independent of notice identity."""
import copy
import json
from pathlib import Path

import pytest

from app.extract.application_regions import explicit_applicant_regions, region_catalog
from app.extract.official_rules import document_cutoff, parse_official_rules
from app.qualification import coverage_scope_complete, public_classification, source_bound_waivers


SOURCES = json.loads((Path(__file__).parent / "fixtures/official-unranked-current-20261012.json").read_text())


def source(number):
    return copy.deepcopy(next(row for row in SOURCES if row["house_manage_no"] == number))


def parse(row, **changes):
    return parse_official_rules(row["pages"], url=row["document_url"], digest=row["document_hash"], payload={
        "title": row["title"], "category": "unsold", "announcement_date": row["announcement_date"],
        "official_url": "https://www.applyhome.co.kr/ai/aia/selectAPTRemndrLttotPblancDetailView.do?houseManageNo=" + row["house_manage_no"],
        **changes,
    })


def one(result, kind):
    return next(rule for rule in result["rules"] if rule["kind"] == kind)


@pytest.mark.parametrize("number,kind,regions,original", [
    ("2026910260", "private", ["11", "28", "41"], "2026-08-13"),
    ("2026910254", "national", ["26"], "2022-10-21"),
    ("2026910255", "national", ["26"], "2022-06-24"),
])
def test_real_current_documents_compare_current_applicants_and_retain_restrictions(number, kind, regions, original):
    row = source(number)
    result = parse(row)
    assert result["status"] == "complete"
    assert public_classification(result["rules"])[0] == kind
    assert [region["region_code"] for region in one(result, "applicant_regions")["regions"]] == regions
    assert one(result, "applicant_regions")["priority_applicable"] is False
    context = one(result, "qualification_context")["value"]
    assert context["original_announcement_date"] == original
    assert context["application_criterion_date"] == "2026-10-12"
    assert {rule["criterion_date"] for rule in result["rules"]} == {"2026-10-12"}
    coverage = one(result, "condition_coverage")
    assert coverage_scope_complete(coverage["scopes"][0])
    assert coverage["scopes"][0]["reviewed_document_hash"] == row["document_hash"]
    assert coverage["scopes"][0]["reviewed_pages"] == list(range(1, len(row["pages"]) + 1))
    assert {rule["restriction"] for rule in result["rules"] if rule["kind"] == "application_restriction"} >= {
        "prior_project_contract", "prior_project_winner", "ineligible_restriction_active", "resale_restriction_active",
    }


@pytest.mark.parametrize("number", ["2026910254", "2026910255"])
def test_public_current_offer_income_assets_waivers_do_not_waive_project_history(number):
    row = source(number)
    result = parse(row)
    assert set(one(result, "condition_exemptions")["topics"]) == {"account", "income", "assets", "rewinning_restriction"}
    coverage = one(result, "condition_coverage")
    waivers = source_bound_waivers(coverage, digest=row["document_hash"], parser_version=result["parser_version"])
    assert {kind for kind, _ in waivers} == {"monthly_income_max_krw", "real_estate_max_krw"}
    assert all(topic["evidence_page"] == 1 and "소득·자산 요건을 불문" in topic["evidence_text"] for _, topic in waivers)
    assert all(not rule["value"] for rule in result["rules"] if rule.get("restriction", "").startswith("prior_project_"))


def test_new_identity_hash_date_and_table_locations_need_no_project_registry():
    row = source("2026910255")
    for page in row["pages"]:
        page["text"] = page["text"].replace(row["title"], "새로운 공공분양 단지").replace("2026910255", "2027999123").replace("2026.10.12", "2027.03.15")
        page["page"] += 7
    row.update(title="새로운 공공분양 단지", house_manage_no="2027999123", announcement_date="2027-03-15", document_hash="new-current-document")
    row["document_url"] = row["document_url"].replace("2026910255", "2027999123")
    result = parse(row)
    assert result["status"] == "complete"
    assert one(result, "applicant_regions")["criterion_date"] == "2027-03-15"
    assert one(result, "applicant_regions")["document_hash"] == "new-current-document"
    assert [region["region_code"] for region in one(result, "applicant_regions")["regions"]] == ["26"]
    assert one(result, "condition_coverage")["scopes"][0]["reviewed_section_pages"] == [11]


@pytest.mark.parametrize("geography,expected", [
    ("수도권에 거주하는", ["11", "28", "41"]),
    ("수 도 권 지역에 거 주하는", ["11", "28", "41"]),
    ("수도권(경기도)에 거주하는", ["41"]),
    ("비수도권에 거주하는", []),
    ("수도권(서울특별시 제외)에 거주하는", []),
])
def test_capital_group_is_applicant_reference_data_and_preserves_explicit_narrowing(geography, expected):
    pages = [{"page": 4, "text": "입주자 모집공고일 현재 " + geography + " 무주택 세대구성원"}]
    provinces = {row["name"]: row["code"] for row in region_catalog()["provinces"]}
    rules = explicit_applicant_regions(pages, cutoff="2026-10-12", provinces=provinces, make=lambda kind, **fields: {"kind": kind, **fields})
    assert [region["region_code"] for rule in rules for region in rule.get("regions", [])] == expected


def test_group_in_address_or_bank_amounts_cannot_create_applicant_scope():
    pages = [{"page": 1, "text": "공급위치 수도권 서울특별시. 입주자모집공고일 현재 청약예금은 수도권 거주자에게 300만원입니다."}]
    provinces = {row["name"]: row["code"] for row in region_catalog()["provinces"]}
    assert explicit_applicant_regions(pages, cutoff="2026-10-12", provinces=provinces, make=lambda kind, **fields: {"kind": kind, **fields}) == []


def test_current_date_conflicts_cannot_pick_the_first_or_initial_cutoff():
    row = source("2026910255")
    row["pages"][1]["text"] = row["pages"][1]["text"].replace("금회 입주자모집공고일은 2026.10.12.", "금회 입주자모집공고일은 2026.10.13.")
    assert document_cutoff(row["pages"], method="unranked_after") == (None, None)
    assert parse(row)["status"] != "complete"


@pytest.mark.parametrize("has_old_context", [False, True])
def test_changed_current_feed_date_cannot_be_masked_by_carried_same_hash_context(has_old_context):
    row = source("2026910260")
    old = [{"kind": "qualification_context", "verification": "official", "document_hash": row["document_hash"],
            "value": {"original_announcement_date": "2026-08-13", "application_criterion_date": "2026-10-12"}}]
    result = parse(row, announcement_date="2026-10-13", rules=old if has_old_context else [], document_hash=row["document_hash"])
    assert result["status"] == "unsupported"
    assert result["identity_status"] == "mismatch"
    assert result["rules"] == []


def test_fresh_current_feed_and_document_beat_a_stale_application_cutoff():
    row = source("2026910260")
    old = [{"kind": "qualification_context", "verification": "official",
            "value": {"original_announcement_date": "2026-08-13", "application_criterion_date": "2026-10-11"}}]
    result = parse(row, rules=old)
    assert result["status"] == "complete"
    assert one(result, "qualification_context")["value"]["application_criterion_date"] == "2026-10-12"


@pytest.mark.parametrize("source_statement,accepted", [
    ("정정공고일은 2026.10.13.이며 청약자격 판단기준일은 2026.10.12.입니다.", True),
    ("정정공고일은 2026.10.14.이며 청약자격 판단기준일은 2026.10.12.입니다.", False),
    ("정정공고일은 2026.10.13.이며 청약자격 판단기준일은 2026.10.11.입니다.", False),
    ("정정공고이며 청약자격 판단기준일은 변경되지 않습니다.", False),
    ("", False),
])
def test_correction_publication_needs_current_source_proof_of_both_dates(source_statement, accepted):
    row = source("2026910260")
    row["title"] = "[정정공고] " + row["title"]
    row["pages"].append({"page": 13, "text": source_statement})
    old = [{"kind": "qualification_context", "verification": "official", "value": {"application_criterion_date": "2026-10-12"}}]
    result = parse(row, announcement_date="2026-10-13", rules=old)
    assert (result["status"] == "complete") is accepted
    if accepted:
        context = one(result, "qualification_context")
        assert context["value"]["correction_publication_date"] == "2026-10-13"
        assert context["value"]["application_criterion_date"] == "2026-10-12"
        assert context["correction_evidence_page"] == 13
        assert source_statement.removesuffix(".입니다.") in context["evidence_text"]
    else:
        assert result["identity_status"] == "mismatch"


def test_inherited_initial_source_does_not_replace_current_operative_scope():
    row = source("2026910260")
    row["pages"].append({"page": 13, "text": "최초 입주자모집공고일(2026.08.13.) 현재 의왕시에 거주하는 무주택세대구성원"})
    result = parse(row)
    assert result["status"] == "complete"
    assert [region["region_code"] for region in one(result, "applicant_regions")["regions"]] == ["11", "28", "41"]


@pytest.mark.parametrize("where", ["table", "general_notes"])
def test_new_mandatory_condition_outside_known_table_remains_concrete_source_gap(where):
    row = source("2026910255")
    page = row["pages"][3 if where == "table" else 1]
    page["text"] += "\n■ 신청자는 근로소득세를 5년 이상 납부하여야 신청할 수 있습니다.\n"
    result = parse(row)
    assert result["status"] == "partial"
    assert any("5년" in topic for scope in one(result, "condition_coverage")["scopes"] for topic in scope["missing_topics"])


@pytest.mark.parametrize("extra", [
    "신청자는 부양기간이 4년 이상이어야 하며 그 사실의 증명서를 제출해야 합니다.",
    "신청자는 근로소득세를 5년 이상 납부하여야 하며 관련 서류를 제출해야 합니다.",
    "신청자는 4년 이상 부양한 부모의 증명서를 제출하여야 합니다.",
])
def test_substantive_admission_condition_is_not_waived_by_its_proof_instructions(extra):
    row = source("2026910255")
    row["pages"][1]["text"] += "\n■ " + extra + "\n"
    result = parse(row)
    assert result["status"] == "partial"
    assert any("미처리 신청자 필수 조건" in topic for scope in one(result, "condition_coverage")["scopes"] for topic in scope["missing_topics"])


@pytest.mark.parametrize("extra", [
    "신청자는 신청서류를 제출하여야 합니다.",
    "신청자는 본인의 인증서를 발급받아야 합니다.",
    "신청자는 신청내용을 입력하여야 합니다.",
    "신청자는 계약금을 납부하여야 합니다.",
    "신청자는 인지세를 납부해야 합니다.",
])
def test_pure_document_entry_or_fee_procedures_are_not_unknown_eligibility(extra):
    row = source("2026910255")
    row["pages"][1]["text"] += "\n■ " + extra + "\n"
    assert parse(row)["status"] == "complete"
