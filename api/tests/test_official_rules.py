import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from app.extract.official_rules import parse_official_rules
from app.extract.pipeline import document_pages, enrich_notice, find_document_links
from app.extract.reviewed_sources import REVIEWED_SOURCES, reviewed_document_url

FIXTURES = json.loads((Path(__file__).parent / "fixtures/official-rules-reviewed.json").read_text())


def fixture(number):
    return next(f for f in FIXTURES if f["house_manage_no"] == number)


def parsed(number):
    f = fixture(number)
    return parse_official_rules(f["pages"], url=f["document_url"], digest=f["document_hash"])


def walk(rules):
    for rule in rules:
        yield rule
        yield from walk(rule.get("conditions", []))
        yield from walk(rule.get("exceptions", []))


def test_real_private_and_national_rank_periods_do_not_share_special_periods():
    private = parsed("2026000494")
    national = parsed("2026000414")
    p_rank = [r for r in private["rules"] if r.get("purpose") == "first_rank"]
    n_rank = [r for r in national["rules"] if r.get("purpose") == "first_rank"]
    assert next(r for r in p_rank if r["kind"] == "private_rank_months")["value"] == 6
    assert next(r for r in n_rank if r["kind"] == "national_rank_months")["value"] == 12
    assert next(r for r in n_rank if r["kind"] == "recognized_payments_min")["value"] == 12
    assert next(r for r in national["rules"] if r["kind"] == "recognized_payments_min" and r.get("supply_type") == "다자녀가구 특별공급")["value"] == 6
    assert not any(r.get("rank_rules_complete") for r in [*p_rank, *n_rank])


def test_real_private_deposit_table_keeps_residence_area_units_and_cutoff():
    rule = next(r for r in parsed("2026000494")["rules"] if r["kind"] == "deposit_min_krw" and r.get("purpose") == "first_rank")
    assert rule["deposit_table"][0] == {"max_area_sqm": 85, "amounts_krw": {"seoul_busan": 3000000, "other_metropolitan": 2500000, "other": 2000000}}
    assert rule["deposit_table"][2]["amounts_krw"]["seoul_busan"] == 10000000
    assert rule["criterion_date"] == "2026-10-02"
    assert rule["evidence_page"] == 23
    assert rule["unit"] == "KRW"


def test_real_special_conditions_are_scoped_to_actual_offered_types():
    result = parsed("2026000494")
    child = next(r for r in result["rules"] if r["kind"] == "children_min")
    assert child["supply_type"] == "다자녀가구 특별공급"
    assert (child["value"], child["child_age_max"], child["child_age_inclusive"]) == (2, 19, False)
    assert child["include_pregnancy"] is True and child["include_adoption"] is True
    marriage = next(r for r in result["rules"] if r["kind"] == "marriage_months_max")
    assert marriage["supply_type"] == "신혼부부 특별공급"
    assert marriage["anniversary_limit"] is True
    assert marriage["exceptions"][0]["verification"] == "official"
    assert "청년 특별공급" not in result["offered_supply_types"]
    coverage = next(r for r in result["rules"] if r["kind"] == "condition_coverage")
    assert all(scope["complete"] is False for scope in coverage["scopes"])
    assert coverage["verification"] == "official" and coverage["effect"] == "metadata"
    newborn = next(r for r in result["rules"] if r["kind"] == "newborn_children_min")
    assert newborn["include_pregnancy"] is True  # Original says 임신중, not 태아.
    assert newborn["include_adoption"] is True
    assert newborn["child_age_inclusive"] is True
    assert "임신중이거나 입양한 경우 포함" in newborn["evidence_text"]


def test_real_national_newlywed_keeps_child_and_family_alternative_branches():
    rules = list(walk(parsed("2026000414")["rules"]))
    family = next(r for r in rules if r.get("label") == "신혼부부 특별공급의 신청 가족 유형")
    assert family["kind"] == "any"
    assert family["conditions"][1]["kind"] == "unparsed"
    assert "예비신혼부부" in family["conditions"][1]["evidence_text"]
    assert any(r.get("child_age_max") == 7 and r.get("child_age_inclusive") is False for r in rules)


def test_real_shinhee_is_not_forced_into_general_first_rank_or_seven_years_only():
    result = parsed("2026820010")
    assert result["offered_supply_types"] == ["신혼부부(신혼희망타운)", "예비신혼부부(신혼희망타운)", "한부모가족(신혼희망타운)"]
    assert not any(r.get("purpose") == "first_rank" for r in result["rules"])
    rules = list(walk(result["rules"]))
    alternatives = next(r for r in rules if r.get("label") == "혼인·자녀 요건")
    assert alternatives["kind"] == "any"
    assert [r["kind"] for r in alternatives["conditions"]] == ["marriage_months_max", "children_min"]


@pytest.mark.parametrize("number", ["2026000494", "2026000414", "2026820010"])
def test_official_facts_have_document_hash_page_cutoff_and_original_evidence(number):
    f = fixture(number)
    assert f["document_hash"] == REVIEWED_SOURCES[number]["document_hash"]
    rules = list(walk(parsed(number)["rules"]))
    assert rules
    for rule in rules:
        assert rule["verification"] == "official"
        assert rule["document_hash"] == f["document_hash"]
        assert rule["criterion_date"] == f["announcement_date"]
        assert rule["evidence_url"] == f["document_url"]
        assert rule.get("evidence_page") in [p["page"] for p in f["pages"]]
        assert rule.get("evidence_text")


def test_official_hangang_visual_heading_order_keeps_newlywed_separate_from_elder():
    # Actual PDF's content stream places the 신혼 heading AFTER its table.
    # Coordinate layout places page14 heading before 6-month qualification;
    # page16 elderly 12-month requirement belongs to its own supply type.
    f = json.loads((Path(__file__).parent / "fixtures/official-rules-hangang-layout.json").read_text())
    result = parse_official_rules(f["pages"], url=f["document_url"], digest=f["document_hash"])
    durations = {r.get("supply_type", "일반공급"): r for r in result["rules"] if r["kind"] == "private_rank_months"}
    assert (durations["신혼부부 특별공급"]["value"], durations["신혼부부 특별공급"]["evidence_page"]) == (6, 14)
    assert (durations["노부모부양 특별공급"]["value"], durations["노부모부양 특별공급"]["evidence_page"]) == (12, 16)
    assert durations["일반공급"]["value"] == 12
    assert "6개월" in durations["신혼부부 특별공급"]["evidence_text"]


def test_city_qualification_is_never_widened_to_the_whole_province():
    base = "이 주택의 입주자모집공고일은 2026.10.02. 민영주택 입주자모집공고\n1. 일반공급\n대상자 입주자모집공고일 현재 {}에 거주하는 분"
    city = parse_official_rules([{"page": 1, "text": base.format("경기도 수원시")}], url="https://www.applyhome.co.kr/public.pdf", digest="municipality")
    province = parse_official_rules([{"page": 1, "text": base.format("경기도")}], url="https://www.applyhome.co.kr/public.pdf", digest="province")
    assert not any(r["kind"] == "residence_region" for r in walk(city["rules"]))
    assert next(r for r in walk(province["rules"]) if r["kind"] == "residence_region")["region_code"] == "41"


def test_private_special_account_period_never_comes_from_selection_score():
    base = "이 주택의 입주자모집공고일은 2026.10.02. 민영주택 입주자모집공고\n1. 신혼부부 특별공급\n대상자 입주자모집공고일 현재 무주택세대구성원\n{}\n당첨자 선정방법\n청약통장 가입기간 12개월 이상 배점"
    url = "https://www.applyhome.co.kr/public.pdf"
    only_score = parse_official_rules([{"page": 1, "text": base.format("")}], url=url, digest="score-only")
    qualified = parse_official_rules([{"page": 1, "text": base.format("청약통장 가입기간 6개월 경과")}], url=url, digest="qualified")
    assert not any(r["kind"] == "private_rank_months" for r in only_score["rules"])
    assert next(r for r in qualified["rules"] if r["kind"] == "private_rank_months")["value"] == 6


def test_decisive_original_phrase_is_present_in_later_page_evidence():
    rules = list(walk(parsed("2026000494")["rules"]))
    assert "소유" in next(r for r in rules if r["kind"] == "never_owned_home")["evidence_text"]
    assert "세대주" in next(r for r in rules if r["kind"] == "household_head")["evidence_text"]
    f = json.loads((Path(__file__).parent / "fixtures/official-rules-hangang-layout.json").read_text())
    later = parse_official_rules(f["pages"], url=f["document_url"], digest=f["document_hash"])["rules"]
    tax = next(r for r in later if r["kind"] == "tax_years_min")
    assert "소득세" in tax["evidence_text"] and tax["evidence_page"] == 18


def test_dates_classification_and_unmatched_context_cannot_be_guessed():
    f = fixture("2026000494")
    assert parse_official_rules([{"page": 1, "text": "입주자모집공고 1순위 6개월 예치금"}], url=f["document_url"], digest="unknown")["rules"] == []
    conflict = {"rules": [{"kind": "qualification_context", "value": {"original_announcement_date": "2026-09-02"}}]}
    assert parse_official_rules(f["pages"], url=f["document_url"], digest=f["document_hash"], payload=conflict)["rules"] == []
    ai = {"rules": [{"kind": "housing_classification", "verification": "ai_unverified", "housing_kind": "national"}]}
    result = parse_official_rules(f["pages"], url=f["document_url"], digest=f["document_hash"], payload=ai)
    assert all(r.get("housing_kind") == "private" for r in result["rules"])


def test_result_table_mentions_and_score_periods_are_not_supply_inventory_or_requirements():
    f = fixture("2026000494")
    stray = [{"page": 1, "text": "본 주택의 최초 입주자모집공고일은 2026.10.02입니다. 민영주택으로 공급하는 입주자모집공고\n기관추천 특별공급 10세대\n신혼부부 특별공급\n청약통장 가입기간 배점 24개월\n"}]
    result = parse_official_rules(stray, url=f["document_url"], digest="stray")
    assert result["offered_supply_types"] == []
    assert not any(r.get("effect") != "metadata" for r in result["rules"])


def test_lh_public_javascript_route_is_translated_without_executing_arbitrary_script():
    html = '<a href="javascript:fileDownLoad(\'123\');">모집공고문.hwpx</a><a href="javascript:fileDownLoad(\'124\');">모집공고문.pdf</a><a href="javascript:fetch(\'https://evil.example\')">공고문.pdf</a>'
    assert find_document_links(html, "https://apply.lh.or.kr/lhapply/notices") == ["https://apply.lh.or.kr/lhapply/lhFile.do?fileid=124", "https://apply.lh.or.kr/lhapply/lhFile.do?fileid=123"]
    assert find_document_links(html, "https://www.applyhome.co.kr/notices") == []


def hwpx_bytes(text):
    import html
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Contents/section0.xml", "<root>" + "".join("<p>" + html.escape(line) + "</p>" for line in text.splitlines()) + "</root>")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_free_model_quota_keeps_locally_verified_conditions_and_prices(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-free-key")
    monkeypatch.setenv("GEMINI_UNBILLED_PROJECT_CONFIRMED", "1")
    data = hwpx_bytes("민영주택으로 공급하는 입주자모집공고\n본 주택의 최초 입주자모집공고일은 2026.10.02입니다.\n5 일반공급 (「주택공급에 관한 규칙」 제28조)\n대상자 청약예금에 가입하여 6개월이 경과하고 지역별 예치금액 이상인 분")
    seen = []
    def handler(request):
        seen.append(request.url.host)
        if request.url.host == "apply.lh.or.kr":
            return httpx.Response(200, content=data)
        return httpx.Response(429)
    original = {"official_url": "https://apply.lh.or.kr/notice.hwpx", "prices": [{"unit_type": "84", "amount_krw": 300000000, "verification": "official"}]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await enrich_notice(original, client)
    assert result["extraction_status"] == "quota"
    assert result["prices"] == original["prices"]
    assert any(r["kind"] == "private_rank_months" and r["verification"] == "official" for r in result["rules"])
    seen.clear()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        waiting = await enrich_notice(original, client, allow_gemini=False)
    assert "generativelanguage.googleapis.com" not in seen
    assert any(r["kind"] == "private_rank_months" for r in waiting["rules"])


@pytest.mark.asyncio
async def test_changed_unreadable_document_retires_old_verified_parser_facts():
    old = {"kind": "private_rank_months", "verification": "official", "source": "official_document_parser", "document_hash": "old", "value": 6}
    notice = {"official_url": "https://apply.lh.or.kr/notice.pdf", "rules": [old], "rules_complete": True}
    data = b"%PDF-1.4\nnot a readable PDF"
    def handler(request):
        return httpx.Response(200, content=data)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await enrich_notice(notice, client, known_document_hash="old", allow_gemini=False)
    assert result["document_hash"] == hashlib.sha256(data).hexdigest()
    assert not any(r["kind"] == "private_rank_months" for r in result["rules"])
    assert result["rules_complete"] is False
    assert result["replace_rules"] is True
    assert {r["kind"] for r in result["rules"]} == {"condition_coverage", "document_diagnostics"}
    diagnostics = next(r for r in result["rules"] if r["kind"] == "document_diagnostics")
    assert any(entry["code"] == "document_decode_failed" for entry in diagnostics["diagnostics"])


def test_reviewed_crosslinks_are_exact_notice_ids_not_title_similarity():
    assert reviewed_document_url("https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=2026000414&pblancNo=2026000414") == REVIEWED_SOURCES["2026000414"]["document_url"]
    assert reviewed_document_url("https://www.applyhome.co.kr/?houseManageNo=2026000414&pblancNo=2026820010") is None
    assert reviewed_document_url("https://evil.example/?houseManageNo=2026000414&pblancNo=2026000414") is None
