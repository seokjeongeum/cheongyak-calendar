"""Whole current LH sources certify supported personal applicant branches."""
import copy
import json
from pathlib import Path

import pytest

from app.extract.official_rules import parse_official_rules


SOURCES = json.loads((Path(__file__).parent / "fixtures/lh-residual-general-sale-20261012.json").read_text())


def parse(row):
    return parse_official_rules(row["pages"], url=row["document_url"], digest=row["document_hash"], payload=row["payload"])


def rule(result, kind):
    return next(item for item in result["rules"] if item["kind"] == kind)


@pytest.mark.parametrize("source", SOURCES, ids=lambda row: row["case"])
def test_actual_whole_sources_have_certified_personal_branches_and_explicit_waivers(source):
    result = parse(source)
    assert result["status"] == "complete"
    assert rule(result, "application_method")["value"] == "first_come"
    scope = rule(result, "condition_coverage")["scopes"][0]
    assert scope["complete"] and scope["missing_topics"] == scope["source_gaps"] == []
    assert scope["review_version"] == "generic-admission-2026-10-12-public-v1"
    assert scope["reviewed_document_hash"] == source["document_hash"]
    assert scope["reviewed_pages"] == list(range(1, len(source["pages"]) + 1))
    assert scope["completion_basis"] == "current_document_clause_coverage"
    assert {branch["branch_id"] for branch in scope["branches"]} >= {"adult", "provider_employee", "corporate"}
    corporation = next(branch for branch in scope["branches"] if branch["branch_id"] == "corporate")
    assert corporation["required"] is False and corporation["status"] == "not_applicable"
    regions = rule(result, "applicant_regions")
    assert regions["scope_complete"] and regions["unrestricted"] and regions["domestic_only"]
    assert rule(result, "domestic_residence")["criterion_date"] == source["payload"]["announcement_date"]
    assert rule(result, "domestic_residence")["criterion_basis"] == "announcement"
    assert set(rule(result, "condition_exemptions")["topics"]) >= {"account", "home_ownership", "prior_win", "income", "assets", "rewinning_restriction"}


@pytest.mark.parametrize("source", SOURCES[:2], ids=lambda row: row["case"])
def test_statutory_employee_family_exception_is_preserved_through_actual_prohibition(source):
    result = parse(source)
    employee = rule(result, "provider_employee_restriction")
    assert employee["restriction_uncertain"] is False
    assert employee["criterion_basis"] == "contract_date" and employee["criterion_date"] is None
    assert "계약을 체결할 수 없습니다" in employee["evidence_text"]
    assert employee["related_family_legal_basis"] == "공직자윤리법 제4조제1항제2호·제3호"
    assert employee["related_family_exclusions"] == [{"legal_basis": "공직자윤리법 제12조제4항", "reason": "재산등록사항 고지 거부 허가"}]
    assert rule(result, "citizenship")["allowed_values"] == ["korean"]
    assert not any(item["kind"] == "minor_household_head" for item in result["rules"])
    instructions = rule(result, "application_instructions")["instructions"]
    assert any(item["label"] == "1인 1주택 신청·계약" and item["phase"] == "application" for item in instructions)
    assert any(item["label"] == "토지거래허가 사전협의·서류 제출" and item["phase"] == "contract" for item in instructions)
    assert any(item["label"] == "기존 공사 임대주택의 반환" and item["phase"] == "occupancy" for item in instructions)


def test_yangsan_minor_alternative_and_principled_employee_restriction_remain_source_bound():
    result = parse(SOURCES[2])
    adult, minor = rule(result, "any")["conditions"]
    assert adult["kind"] == "age_min" and adult["value"] == 19
    assert minor["kind"] == "minor_household_head" and minor["required_same_register"]
    assert minor["reasons"] == ["support_children", "support_siblings_parents_dead_or_missing"]
    assert "등재되어 있어야 합니다" in minor["evidence_text"]
    employee = rule(result, "provider_employee_restriction")
    assert employee["restriction_uncertain"] is True
    assert employee["related_family_scope"] == "배우자 및 임직원 본인의 직계존·비속"
    assert "원칙적으로 제한" in employee["evidence_text"]
    assert not any(item["kind"] == "citizenship" for item in result["rules"])


def test_changed_minor_alternative_does_not_invent_omitted_sibling_or_child_permission():
    source = copy.deepcopy(SOURCES[2])
    page = source["pages"][2]
    page["text"] = " ".join(page["text"].split())
    original = "미성년자는 직계존속의 사망, 실종선고 및 행방불명 등으로 형제자매를 부양해야 하거나, 자녀를 부양하여야 하는 세대주만 신청 가능합니다."
    assert original in page["text"]
    page["text"] = page["text"].replace(original, "미성년자는 자녀를 부양하여야 하는 세대주만 신청 가능합니다.")
    result = parse(source)
    minor = rule(result, "any")["conditions"][1]
    assert minor["reasons"] == ["support_children"]
    assert result["status"] == "complete"


def test_missing_minor_same_register_requirement_cannot_certify_its_alternative():
    source = copy.deepcopy(SOURCES[2])
    source["pages"][2]["text"] = source["pages"][2]["text"].replace("등재되어 있어야 합니다", "미확보 문장")
    scope = rule(parse(source), "condition_coverage")["scopes"][0]
    assert not scope["complete"]
    assert any("미성년 세대주" in topic for topic in scope["missing_topics"])


def test_independent_identity_hash_date_page_position_and_age_use_current_source_values():
    source = copy.deepcopy(SOURCES[0])
    source["document_hash"] = "new-independent-whole-lh-source"
    source["document_url"] = "https://apply.lh.or.kr/lhapply/lhFile.do?fileid=99999001"
    source["payload"].update(title="새 도시 잔여세대 일반매각 공고", external_id="2034000000000001", announcement_date="2034-09-18",
                             official_url="https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do?panId=2034000000000001")
    for page in source["pages"]:
        page["page"] += 11
        page["text"] = page["text"].replace("2026.09.18", "2034.09.18").replace("2026. 09. 18", "2034. 09. 18").replace("19세 이상", "21세 이상")
    result = parse(source)
    assert result["status"] == "complete"
    age = rule(result, "age_min")
    assert age["value"] == 21 and age["criterion_date"] == "2034-09-18"
    assert age["evidence_page"] == 17
    assert all(item["document_hash"] == source["document_hash"] and item["evidence_url"] == source["document_url"] for item in result["rules"])
    assert rule(result, "condition_coverage")["scopes"][0]["reviewed_pages"] == list(range(12, 21))


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("removed", ["middle", "last"])
def test_missing_whole_source_pages_never_certify(index, removed):
    source = copy.deepcopy(SOURCES[index])
    source["pages"].pop(len(source["pages"]) // 2 if removed == "middle" else -1)
    result = parse(source)
    scope = rule(result, "condition_coverage")["scopes"][0]
    assert result["status"] == "partial" and not scope["complete"]
    assert any(gap["stage"] == "document_text" for gap in scope["source_gaps"])


@pytest.mark.parametrize("clause", [
    "■ 자동차가액 4,500만원 이하인 자만 신청 가능합니다.",
    "■ 신청자는 장애인 등록을 하여야 합니다.",
    "■ 무주택 세대주만 신청 가능합니다.",
    "■ 신청자는 공급기관 사전승인이 있어야 합니다. 관련 서류를 제출합니다.",
    "■ 신청자는 공급기관 사전승인을 받아야 합니다.",
    "■ 신청자는 장애인 등록을 해야 하며 현장확인 서류를 제출합니다.",
])
def test_new_mandatory_clauses_retain_their_specific_current_page_evidence(clause):
    source = copy.deepcopy(SOURCES[0])
    source["pages"][5]["text"] += "\n" + clause
    result = parse(source)
    scope = rule(result, "condition_coverage")["scopes"][0]
    assert not scope["complete"]
    assert any(clause[2:] in gap.get("evidence_text", "") and gap["evidence_page"] == 6 for gap in scope["source_gaps"])


def test_unknown_requirement_sharing_modeled_age_value_remains_unmodeled():
    source = copy.deepcopy(SOURCES[0])
    source["pages"][5]["text"] = source["pages"][5]["text"].replace("만19세 이상인 자", "만19세 이상이며 근무기간 19년 이상인 자만 신청 가능한 자")
    scope = rule(parse(source), "condition_coverage")["scopes"][0]
    assert not scope["complete"]
    assert any("근무기간 19년" in gap.get("evidence_text", "") for gap in scope["source_gaps"])


def test_source_privacy_consent_procedure_does_not_hide_a_second_eligibility_gate():
    source = copy.deepcopy(SOURCES[0])
    consent = "청약자는 청약 시 ‘개인정보 제공 및 활용’과 ‘정보의 제3자 제공’에 동의해야 합니다."
    source["pages"][5]["text"] += "\n■ " + consent
    assert parse(source)["status"] == "complete"
    source["pages"][5]["text"] += " 신청자는 공급기관 사전승인을 받아야 합니다."
    scope = rule(parse(source), "condition_coverage")["scopes"][0]
    assert not scope["complete"]
    assert any("사전승인" in gap["evidence_text"] for gap in scope["source_gaps"])


def test_mandatory_account_clause_is_not_waived_by_another_subjects_unrestricted_region():
    source = copy.deepcopy(SOURCES[0])
    source["document_hash"] = "new-account-requirement-source"
    for page in source["pages"]:
        page["text"] = page["text"].replace("주택청약종합저축 가입 여부", "주택청약종합저축에 가입하여야 하고 거주지역")
    result = parse(source)
    scope = rule(result, "condition_coverage")["scopes"][0]
    assert not scope["complete"]
    assert any("청약통장 가입 필수" in topic for topic in scope["missing_topics"])
    assert any("주택청약종합저축에 가입하여야" in gap["evidence_text"] for gap in scope["source_gaps"])


def test_different_source_announcement_date_does_not_reuse_prior_review():
    source = copy.deepcopy(SOURCES[0])
    source["payload"]["announcement_date"] = "2026-09-19"
    result = parse(source)
    assert result["status"] == "unsupported"
    assert not any(item["kind"] == "condition_coverage" for item in result["rules"])


def test_conflicting_operative_applicant_date_is_reported_separately_from_paperwork_dates():
    source = copy.deepcopy(SOURCES[0])
    source["document_hash"] = "new-date-conflict-source"
    source["pages"][5]["text"] = source["pages"][5]["text"].replace("공고일(2026.09.18.) 기준", "공고일(2026.09.19.) 기준")
    result = parse(source)
    scope = rule(result, "condition_coverage")["scopes"][0]
    assert not scope["complete"]
    assert any(gap["stage"] == "criterion_date" and gap["evidence_page"] == 6 and "2026.09.19" in gap["evidence_text"] for gap in scope["source_gaps"])
