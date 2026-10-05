"""Official contract timing and the fully reviewed Cheongju admission section."""
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from app.extract.contract_schedule import parse_contract_schedule
from app.extract.official_rules import PARSER_VERSION, parse_official_rules, parser_version_usable
from app.extract.reprocess import _document_patch
from app.qualification import public_contract_schedule, requirements_complete
from app.repository import notice_public, upsert_notice
from test_repository_api import db, client, example_notice


FIXTURE = json.loads((Path(__file__).parent / "fixtures/cheongju-contract-v6.json").read_text())


def parse_cheongju(*, digest=None, pages=None):
    return parse_official_rules(pages or FIXTURE["pages"], url=FIXTURE["document_url"],
        digest=digest or FIXTURE["document_hash"], payload=FIXTURE["payload"])


def test_cheongju_full_admission_review_and_open_contract_dates():
    result = parse_cheongju()
    assert result["status"] == "complete"
    assert requirements_complete(result["rules"], False)
    coverage = next(r for r in result["rules"] if r["kind"] == "condition_coverage")
    assert coverage["scopes"][0]["complete"] is True
    assert coverage["scopes"][0]["missing_topics"] == []
    assert {r["kind"] for r in result["rules"] if r.get("effect") != "metadata"} == {
        "any", "domestic_residence", "citizenship", "provider_employee_restriction"}
    age = next(r for r in result["rules"] if r["kind"] == "any")
    assert age["conditions"][0]["kind"] == "age_min"
    assert age["conditions"][1]["kind"] == "minor_household_head"
    employee = next(r for r in result["rules"] if r["kind"] == "provider_employee_restriction")
    assert employee["restriction_uncertain"] is True
    exemptions = next(r for r in result["rules"] if r["kind"] == "condition_exemptions")
    assert {"account", "income", "assets", "home_ownership", "prior_win", "prior_project_contract", "rewinning_restriction"} <= set(exemptions["topics"])
    schedule = public_contract_schedule(result["rules"])
    assert schedule.status == "ongoing"
    assert schedule.start_date == date(2026, 7, 23)
    assert schedule.end_date is None
    assert schedule.evidence_page in {1, 8}
    assert schedule.document_hash == FIXTURE["document_hash"]
    assert "별도 공지시까지" in schedule.evidence_text


def test_document_change_or_absent_review_pages_does_not_certify_full_admission():
    changed = parse_cheongju(digest="corrected-file")
    assert changed["status"] == "partial"
    assert not requirements_complete(changed["rules"], True)
    incomplete = parse_cheongju(pages=FIXTURE["pages"][:2])
    assert incomplete["status"] == "partial"


@pytest.mark.parametrize("text,status,start,end", [
    ("계약기간 : 2026.10.12 ~ 2026.10.14", "range", "2026-10-12", "2026-10-14"),
    ("계약일 : 2026년 10월 12일", "fixed", "2026-10-12", "2026-10-12"),
    ("정당계약 2026.10.12.(월) ~ 2026.10.14.(수)", "range", "2026-10-12", "2026-10-14"),
    ("계약체결기간(2026.10.19.~10.20.)", "range", "2026-10-19", "2026-10-20"),
    ("선착순 동호지정 및 계약 일정 ‘26.07.23.(목) 오전 10시 ~ 별도 공지시까지", "ongoing", "2026-07-23", None),
])
def test_explicit_document_contract_schedule(text, status, start, end):
    result = parse_contract_schedule([{"page": 4, "text": text}], url="https://apply.lh.or.kr/public.pdf", digest="document", parser_version=PARSER_VERSION)
    assert result["status"] == status
    assert result["start_date"] == start and result["end_date"] == end
    assert result["evidence_page"] == 4 and result["effect"] == "metadata"


@pytest.mark.parametrize("text", [
    "공고 게시 종료일 2027.07.15. 신청자격은 계약체결일 기준입니다.",
    "접수기간 2026.10.12~2026.10.14. 계약금 납부 준비 안내",
    "계약체결일 현재 국내에 거주하는 성년자. 최초 공고일 2025.11.21.",
    "계약일 2026.02.30.",
    "계약기간 2026.10.14~2026.10.12",
])
def test_non_contract_deadlines_and_invalid_dates_are_not_contract_schedules(text):
    assert parse_contract_schedule([{"page": 1, "text": text}], url="https://apply.lh.or.kr/public.pdf", digest="file", parser_version=PARSER_VERSION) is None


def test_conflicting_contract_schedules_are_unknown_without_guessing():
    result = parse_contract_schedule([{"page": 1, "text": "계약일 2026.10.12. 계약일 2026.10.20."}], url="https://apply.lh.or.kr/public.pdf", digest="file", parser_version=PARSER_VERSION)
    projected = public_contract_schedule([result])
    assert projected.status == "unknown"
    assert projected.start_date is None and projected.end_date is None


def test_table_uses_final_contract_column_and_defers_incomplete_range():
    table = "구분 입주자모집공고일 접수일 서류접수 계약체결\n\n일정 2026.10.02.(금) 2026.10.07.(수) 2026.10.14.(수) 2026.10.21.(수)"
    result = parse_contract_schedule([{"page":1,"text":table}], url="https://apply.lh.or.kr/public.pdf", digest="file", parser_version=PARSER_VERSION)
    assert result["start_date"] == result["end_date"] == "2026-10-21"
    assert parse_contract_schedule([{"page":1,"text":table+" ~\n2026.10.23."}], url="https://apply.lh.or.kr/public.pdf", digest="file", parser_version=PARSER_VERSION) is None


def test_official_document_overrides_feed_and_no_personal_date_used():
    rules = parse_cheongju()["rules"]
    schedule = public_contract_schedule(rules, contract_events=[{"start_date":date(2027,7,15),"end_date":date(2027,7,15)}])
    assert schedule.status == "ongoing" and schedule.start_date == date(2026,7,23)
    assert not public_contract_schedule([]).model_dump().get("intended_contract_date")
    assert public_contract_schedule([{"kind":"contract_schedule","verification":"ai_unverified","status":"fixed","start_date":"2026-10-12","end_date":"2026-10-12"}]).status == "unknown"


def test_existing_official_contract_events_project_to_list_and_detail(db, client):
    raw = example_notice()
    raw["events"].append({"kind":"contract","label":"정당계약","start_date":"2026-10-12","end_date":"2026-10-14"})
    notice = upsert_notice(db, raw)
    db.commit()
    listed = client.get("/api/notices").json()["items"][0]
    detailed = client.get(f"/api/notices/{notice.id}").json()
    assert listed["contract_schedule"] == detailed["contract_schedule"]
    assert listed["contract_schedule"]["status"] == "range"
    assert listed["contract_schedule"]["start_date"] == "2026-10-12"
    assert listed["contract_schedule"]["end_date"] == "2026-10-14"
    assert listed["contract_schedule"]["evidence_url"] == raw["official_url"]


def test_reviewed_contract_metadata_is_preserved_on_poll_and_retired_on_document_change(db, client):
    raw = {**example_notice(source="lh"), **FIXTURE["payload"], "rules":parse_cheongju()["rules"],"document_hash":FIXTURE["document_hash"],"rules_complete":True}
    notice = upsert_notice(db, raw)
    db.commit()
    before = client.get(f"/api/notices/{notice.id}").json()
    assert before["contract_schedule"]["status"] == "ongoing" and before["rules_complete"]
    upsert_notice(db, {"source":raw["source"],"external_id":raw["external_id"],"rules":[]})
    db.commit()
    # Retained source rows' official metadata remains usable after a feed poll.
    assert notice_public([notice]).contract_schedule.status == "ongoing"
    current = copy.deepcopy(raw)
    enriched = {**current, "document_hash":"corrected-file", "rules":parse_cheongju(digest="corrected-file")["rules"]}
    patch = _document_patch(current, enriched)
    assert not patch["rules_complete"]
    assert all(r.get("document_hash") == "corrected-file" for r in patch["rules"] if r.get("source") == "official_document_parser")


def test_v5_existing_interpretations_remain_usable_until_reprocessing():
    assert parser_version_usable({"source":"official_document_parser","parser_version":"official-sections-2026-10-05-v5"}, category="public_sale")
