"""Current residual public sources and independent changed-source regressions."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.extract.official_rules import parse_official_rules


SOURCES = json.loads((Path(__file__).parent / "fixtures/public-residual-admission-20261013.json").read_text())


def parse(source):
    return parse_official_rules(source["pages"], url=source["document_url"],
        digest=source["document_hash"], payload=source["payload"])


def one(result, kind):
    return next(rule for rule in result["rules"] if rule["kind"] == kind)


@pytest.mark.parametrize("source", SOURCES, ids=lambda row: row["case"])
def test_full_current_sources_review_all_pages_at_their_own_hash_and_date(source):
    result = parse(source)
    assert result["status"] == "complete"
    scope = one(result, "condition_coverage")["scopes"][0]
    assert scope["complete"] and scope["source_gaps"] == scope["missing_topics"] == []
    assert scope["completion_basis"] == "current_document_clause_coverage"
    assert scope["reviewed_document_hash"] == source["document_hash"]
    assert scope["reviewed_pages"] == list(range(1, len(source["pages"]) + 1))
    assert one(result, "rank_applicability")["account_required"] is False
    assert one(result, "applicant_regions")["unrestricted"] is True
    assert all(rule["document_hash"] == source["document_hash"] for rule in result["rules"])
    assert all(rule.get("criterion_date") in {None, source["payload"]["announcement_date"]}
        for rule in result["rules"])


@pytest.mark.parametrize("index", [0, 3])
def test_public_officetel_keeps_current_adult_offer_and_resident_foreign_alternative(index):
    result = parse(SOURCES[index])
    assert one(result, "application_method")["value"] == "first_come"
    assert one(result, "housing_classification")["housing_kind"] == "not_applicable"
    assert one(result, "age_min")["value"] == 19
    assert one(result, "age_min")["criterion_date"] == "2026-05-21"
    assert not any(rule["kind"] == "domestic_residence" for rule in result["rules"])
    residence_alternative = one(result, "any")
    assert residence_alternative["conditions"][0]["kind"] == "citizenship"
    assert residence_alternative["conditions"][0]["allowed_values"] == ["korean"]
    assert residence_alternative["conditions"][1]["kind"] == "domestic_residence"
    assert residence_alternative["conditions"][1]["value"] is True
    assert residence_alternative["evidence_page"] == 2
    assert "외국인 포함" in residence_alternative["evidence_text"]
    assert "domestic_residence" in one(result, "condition_coverage")["scopes"][0]["branches"][0]["requirements"]
    inventory = one(result, "supply_inventory_summary")
    assert inventory["total_households"] == 66 and inventory["current_supply_count"] == 15
    exemptions = set(one(result, "condition_exemptions")["topics"])
    assert exemptions >= {"account", "home_ownership"}
    assert not exemptions.intersection({"income", "assets", "prior_win"})


def test_parenthesized_adult_age_reminder_is_a_modeled_predicate_not_a_new_requirement():
    source = SOURCES[5]
    assert "성년자(만 19세 이상" in source["pages"][3]["text"]
    result = parse(source)
    assert one(result, "age_min")["value"] == 19
    assert result["status"] == "complete"
    assert one(result, "age_min")["criterion_date"] == "2026-07-03"


@pytest.mark.parametrize("index", [1, 2])
def test_contract_day_offer_keeps_source_qualification_maintenance_instruction(index):
    result = parse(SOURCES[index])
    assert one(result, "age_min")["criterion_basis"] == "contract_date"
    assert one(result, "age_min")["criterion_date"] is None
    instructions = one(result, "application_instructions")["instructions"]
    maintenance = next(item for item in instructions if item["phase"] == "eligibility_maintenance")
    assert maintenance["label"] == "공고일부터 입주까지 신청자격 유지"
    assert maintenance["document_hash"] == SOURCES[index]["document_hash"]
    assert maintenance["evidence_page"] == 2
    assert maintenance["start_basis"] == "announcement" and maintenance["end_basis"] == "occupancy"
    assert maintenance["start_date"] == SOURCES[index]["payload"]["announcement_date"]
    assert set(maintenance["maintained_rule_ids"]) == {one(result, "age_min")["id"], one(result, "domestic_residence")["id"]}


@pytest.mark.parametrize("index", [0, 5])
@pytest.mark.parametrize("clause", [
    "■ 신청자는 공급기관의 사전승인을 받아야 합니다.",
    "■ 만19세 이상의 성년자로서 근무기간 19년 이상인 자만 신청 가능합니다.",
    "■ 신청자는 등록장애인이어야 합니다.",
])
def test_supported_age_or_broad_office_permission_does_not_hide_extra_gates(index, clause):
    source = copy.deepcopy(SOURCES[index])
    source["pages"][-1]["text"] += "\n" + clause
    result = parse(source)
    assert result["status"] == "partial"
    gaps = one(result, "condition_coverage")["scopes"][0]["source_gaps"]
    assert any(clause[2:] in gap["evidence_text"] for gap in gaps)


def test_new_identity_age_date_and_page_layout_use_source_facts_without_project_exceptions():
    source = copy.deepcopy(SOURCES[0])
    source["payload"].update(title="새 오피스텔 잔여세대 선착순 공고", external_id="next-public-offer",
        official_url="https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do?panId=new-offer",
        announcement_date="2031-05-21")
    source["document_url"] = "https://apply.lh.or.kr/lhapply/lhFile.do?fileid=new-official-file"
    for page in source["pages"]:
        page["page"] += 7
        page["text"] = page["text"].replace("2026.05.21", "2031.05.21").replace("19세", "21세")
    source["document_hash"] = hashlib.sha256(json.dumps(source["pages"]).encode()).hexdigest()
    result = parse(source)
    assert result["status"] == "complete"
    assert one(result, "age_min")["value"] == 21
    assert one(result, "age_min")["criterion_date"] == "2031-05-21"
    assert one(result, "condition_coverage")["scopes"][0]["reviewed_pages"] == [8, 9, 10, 11]
    assert all(rule["evidence_url"] == source["document_url"] and rule["document_hash"] == source["document_hash"]
        for rule in result["rules"])


@pytest.mark.parametrize("source", SOURCES, ids=lambda row: row["case"])
def test_missing_final_page_cannot_reuse_whole_source_completion(source):
    changed = copy.deepcopy(source)
    changed["pages"].pop()
    result = parse(changed)
    assert result["status"] == "partial"
    assert any(gap["stage"] == "document_text" for gap in one(result, "condition_coverage")["scopes"][0]["source_gaps"])


def test_current_office_admission_date_conflict_keeps_source_review_incomplete():
    source = copy.deepcopy(SOURCES[0])
    source["pages"][1]["text"] = source["pages"][1]["text"].replace("입주자모집공고일(2026.05.21.) 현재", "입주자모집공고일(2026.05.20.) 현재")
    result = parse(source)
    assert result["status"] == "partial"
    assert any(gap["stage"] == "criterion_date" for gap in one(result, "condition_coverage")["scopes"][0]["source_gaps"])
