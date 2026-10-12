"""A current public residual offer is interpreted from its operative clauses."""
import copy
import hashlib
import json
from pathlib import Path

from app.extract.official_rules import parse_official_rules
from app.qualification import public_application_method, public_rank_applicability


SOURCE = json.loads((Path(__file__).parent / "fixtures" / "public-first-come-20260710.json").read_text())


def parse(*, pages=None, payload=None, url=None, digest=None):
    return parse_official_rules(pages or SOURCE["pages"], payload=payload or SOURCE["payload"],
        url=url or SOURCE["document_url"], digest=digest or SOURCE["document_hash"])


def one(result, kind):
    return next(rule for rule in result["rules"] if rule["kind"] == kind)


def test_current_outline_title_does_not_hide_actual_first_come_contract_method():
    result = parse()
    assert result["status"] == "complete"
    method, proof = public_application_method(result["rules"])
    assert method == "first_come"
    assert proof.evidence_text == "금회 공급하는 주택은 선착순 동·호지정으로 현장계약만 가능"
    assert one(result, "application_method")["evidence_page"] == 1
    rank = public_rank_applicability(result["rules"])
    assert rank.status == "not_applicable" and rank.account_required is False
    assert "선착순 계약" in rank.reason and "무순위 추첨" not in rank.reason
    scope = one(result, "condition_coverage")["scopes"][0]
    assert scope["reviewed_document_hash"] == SOURCE["document_hash"]
    assert scope["complete"] is True and scope["missing_topics"] == []
    assert one(result, "age_min")["value"] == 19
    assert one(result, "domestic_residence")["value"] is True
    assert one(result, "applicant_regions")["unrestricted"] is True
    assert set(one(result, "condition_exemptions")["topics"]) == {
        "account", "income", "assets", "home_ownership", "prior_win", "rewinning_restriction"}
    assert not any(rule["kind"] in {"homeless", "private_rank_months", "national_rank_months"}
                   for rule in result["rules"])


def test_same_clauses_generalize_to_another_project_document_and_page_layout():
    pages = copy.deepcopy(SOURCE["pages"])
    for page in pages:
        page["page"] += 7
        page["text"] = page["text"].replace("부산연지자이", "새로운공급단지")
    payload = {**SOURCE["payload"], "title": "새로운공급단지 잔여세대 일반매각 공고", "external_id": "new-offer",
        "official_url": "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do?panId=new-offer"}
    digest = hashlib.sha256(json.dumps(pages, ensure_ascii=False).encode()).hexdigest()
    result = parse(pages=pages, payload=payload, digest=digest,
        url="https://apply.lh.or.kr/lhapply/lhFile.do?fileid=new-document")
    assert result["status"] == "complete"
    method, proof = public_application_method(result["rules"])
    assert method == "first_come" and one(result, "application_method")["evidence_page"] == 8
    assert all(rule["document_hash"] == digest for rule in result["rules"])
    assert one(result, "condition_coverage")["scopes"][0]["reviewed_document_hash"] == digest


def test_missing_applicant_page_and_unmodeled_limit_cannot_claim_full_review():
    result = parse(pages=[page for page in SOURCE["pages"] if page["page"] != 3])
    assert result["status"] != "complete"
    assert one(result, "condition_coverage")["scopes"][0]["source_gaps"]
    pages = copy.deepcopy(SOURCE["pages"])
    pages[2]["text"] += "\n■ 자동차가액 4,500만원 이하인 자만 신청 가능합니다."
    result = parse(pages=pages)
    assert result["status"] == "partial"
    assert any("자동차가액" in gap.get("evidence_text", "")
        for gap in one(result, "condition_coverage")["scopes"][0]["source_gaps"])


def test_one_person_one_home_is_an_application_instruction_not_missing_personal_fact():
    result = parse()
    instruction = one(result, "application_instructions")["instructions"]
    assert any(row["label"] == "1인 1주택 신청·계약" and row["phase"] == "application" for row in instruction)
    assert not one(result, "condition_coverage")["scopes"][0]["missing_topics"]


def test_viewing_procedure_cannot_hide_an_added_applicant_approval_requirement():
    pages = copy.deepcopy(SOURCE["pages"])
    clause = "신청자는 공급기관의 사전승인을 받아야 합니다."
    pages[0]["text"] = pages[0]["text"].replace("현장을 확인 후 계약하여야 하며", "현장을 확인 후 계약하여야 하며 " + clause)
    result = parse(pages=pages)
    assert result["status"] == "partial"
    assert any(clause in gap["evidence_text"] for gap in one(result, "condition_coverage")["scopes"][0]["source_gaps"])


def test_incompatible_current_announcement_date_does_not_borrow_old_review():
    result = parse(payload={**SOURCE["payload"], "announcement_date": "2026-07-11"})
    assert result["status"] == "unsupported" and result["identity_status"] == "mismatch"
    assert not result["rules"]


def test_first_come_sentence_inside_an_initial_ranked_offer_is_not_a_residual_application():
    pages = [{"page": 1, "text": "새로운단지 민영주택 입주자모집공고\n"
        "본 주택의 최초 입주자모집공고일은 2026.07.10.입니다.\n"
        "■ 본 아파트는 민영주택으로 공급합니다.\n"
        "■ 일반공급 신청자격: 수도권 거주자로 청약통장 순위별 요건을 충족하는 분.\n"
        "■ 금회 공급하는 주택은 일반공급 1순위로 신청합니다.\n"
        "미계약 잔여주택은 선착순 동·호지정으로 현장계약만 가능합니다."}]
    result = parse(pages=pages, payload={**SOURCE["payload"], "title": "새로운단지 민영주택 입주자모집공고"})
    assert not any(rule["kind"] == "application_method" and rule.get("value") == "first_come" for rule in result["rules"])

