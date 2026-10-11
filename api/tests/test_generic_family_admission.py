"""Family facts follow current source clauses rather than a notice registry."""
import copy
import json
import re
from pathlib import Path

from app.extract.generic_family_admission import generic_family_admission, REVIEW_VERSION

SOURCE = json.loads((Path(__file__).parent / "fixtures/public-v5.json").read_text())[3]


def extract(pages, digest="new-family-document"):
    def make(kind, value=None, *, supply=None, quote="", page=None, **fields):
        rule = {"kind": kind, "document_hash": digest, "evidence_page": page, "evidence_text": quote,
                "evidence_url": "https://apply.lh.or.kr/lhapply/lhFile.do?fileid=99999999", "criterion_date": "2030-09-10",
                "verification": "official", **fields}
        if value is not None:
            rule["value"] = value
        if supply:
            rule["supply_type"] = supply
        return rule
    return generic_family_admission(pages, digest=digest, make=make)


def of(result, kind):
    return [rule for rule in result["rules"] if rule["kind"] == kind]


def walk(rules):
    for rule in rules:
        yield rule
        yield from walk(rule.get("conditions", []))


def new_pages():
    pages = copy.deepcopy(SOURCE["pages"])
    for page in pages:
        page["page"] += 20
        page["text"] = page["text"].replace("2026820010", "2030829999").replace("인천계양", "새로운가족도시").replace("A17", "C99").replace("2026.09.30", "2030.09.10")
    return pages


def test_new_notice_identity_hash_and_page_numbers_keep_source_bound_family_facts():
    result = extract(new_pages())
    assert result["review_version"] == REVIEW_VERSION
    assert result["offered"] == [name + "(신혼희망타운)" for name in ("신혼부부", "예비신혼부부", "한부모가족")]
    assert [r["value"] for r in of(result, "subscription_months")] == [6, 6, 6]
    assert [r["value"] for r in of(result, "recognized_payments_min")] == [6, 6, 6]
    assert of(result, "shinhee_income")[0]["percentage_tables"]["200"][0]["max_krw"] == 15067526
    assert of(result, "shinhee_assets")[0]["two_children_max_krw"] == 431000000
    assert of(result, "shinhee_assets")[0]["evidence_page"] == 31
    assert all(r["document_hash"] == "new-family-document" for r in walk(result["rules"]))
    assert all(r["evidence_page"] > 20 for r in walk(result["rules"]))


def test_new_subscription_child_and_marriage_numbers_come_from_each_qualification():
    pages = new_pages()
    for page in pages:
        page["text"] = page["text"].replace("가입하여 6개월", "가입하여 9개월").replace("월납입금을 6회", "월납입금을 10회")
        page["text"] = page["text"].replace("혼인기간이 7년 이내", "혼인기간이 5년 이내").replace("6세 이하", "8세 이하").replace("만 7세 미만", "만 9세 미만")
    result = extract(pages)
    assert [r["value"] for r in of(result, "subscription_months")] == [9, 9, 9]
    assert [r["value"] for r in of(result, "recognized_payments_min")] == [10, 10, 10]
    conditions = list(walk(result["rules"]))
    assert next(r for r in conditions if r["kind"] == "marriage_months_max")["value"] == 60
    children = [r for r in conditions if r["kind"] == "children_min"]
    assert len(children) == 2 and all(r["child_age_max"] == 9 and not r["child_age_inclusive"] for r in children)
    assert all(r["include_pregnancy"] for r in children)


def test_current_income_amounts_and_asset_limits_do_not_use_annual_constants():
    pages = new_pages()
    for page in pages:
        if "전년도 도시근로자 가구당 월평균소득 기준" in page["text"] and "15,067,526" in page["text"]:
            page["text"] = re.sub(r"(?<![\d,])(\d{1,3}(?:,\d{3})+)(?![\d,])", lambda m: f'{int(m[1].replace(",", "")) * 2:,}', page["text"])
        page["text"] = page["text"].replace("362,000천원", "400,000천원").replace("397,000천원", "440,000천원").replace("431,000천원", "480,000천원").replace("23.3.28", "29.4.15")
    result = extract(pages)
    assert of(result, "shinhee_income")[0]["percentage_tables"]["200"][0]["max_krw"] == 30135052
    assert of(result, "shinhee_income")[0]["child_relaxation_since"] == "2029-04-15"
    assets = of(result, "shinhee_assets")[0]
    assert (assets["base_max_krw"], assets["one_child_max_krw"], assets["two_children_max_krw"]) == (400000000, 440000000, 480000000)


def test_missing_or_conflicting_current_table_does_not_borrow_old_money():
    pages = new_pages()
    for page in pages:
        page["text"] = page["text"].replace("15,067,526", "15,067,527")
    # A conflicting repeat of a printed percentage table must be audited.
    original_table = next(p for p in SOURCE["pages"] if "15,067,526" in p["text"])
    pages.append({**original_table, "page": max(p["page"] for p in pages) + 1})
    result = extract(pages)
    assert not of(result, "shinhee_income")
    assert all(any("공식 금액표" in gap for gap in gaps) for gaps in result["missing_topics"].values())
    pages = [p for p in new_pages() if "15,067,526" not in p["text"]]
    assert not of(extract(pages), "shinhee_income")


def test_incomplete_last_income_row_does_not_use_the_next_footnote_amount():
    pages = new_pages()
    for page in pages:
        page["text"] = page["text"].replace("15,067,526 17,604,404 18,653,970 19,812,526 20,971,082 22,129,638",
                                            "15,067,526 17,604,404 18,653,970 19,812,526 20,971,082")
    result = extract(pages)
    assert not of(result, "shinhee_income")


def test_procedural_or_contents_mentions_do_not_create_a_family_route():
    pages = [{"page": 88, "text": "목차\n2. 신혼부부 신청자격\n3. 당첨자 제출서류\n입주자저축에 가입하여 6개월이 경과되고 월납입금을 6회 이상 납입한 분"}]
    assert extract(pages) is None


def test_unmodeled_planned_household_and_assessment_timing_remain_explicit():
    result = extract(new_pages())
    assert of(result, "unparsed")[0]["label"] == "혼인으로 구성할 세대의 주택 소유"
    assert all(any("평가시점" in gap for gap in gaps) for gaps in result["missing_topics"].values())
    pages = new_pages()
    for page in pages:
        page["text"] = page["text"].replace("4. 한부모가족 신청자격", "⑤ 자동차 가액이 5,000만원 이하인 분\n\n4. 한부모가족 신청자격")
    result = extract(pages)
    assert any("추가 신청자격" in gap for gap in result["missing_topics"]["예비신혼부부(신혼희망타운)"])


def test_changed_child_bonus_is_retained_but_never_uses_the_old_browser_fallback():
    pages = new_pages()
    for page in pages:
        page["text"] = page["text"].replace("10%p", "15%p").replace("20%p", "25%p")
    result = extract(pages)
    for rule in of(result, "shinhee_income") + of(result, "shinhee_assets"):
        assert rule["one_child_bonus_percent"] == 15 and rule["two_children_bonus_percent"] == 25
        assert not rule["child_relaxation_policy_supported"] and rule["child_relaxation_since"] is None
    assert all(any("가산 정책" in topic["topic"] for topic in topics) for topics in result["conditional_topics"].values())


def test_income_and_asset_child_policies_are_not_borrowed_from_each_other():
    pages = new_pages()
    for page in pages:
        if "(출산가구 소득기준 완화)" in page["text"]:
            page["text"] = page["text"].replace("10%p", "15%p").replace("20%p", "25%p")
    result = extract(pages)
    assert of(result, "shinhee_income")[0]["one_child_bonus_percent"] == 15
    assert of(result, "shinhee_income")[0]["child_relaxation_since"] is None
    assert of(result, "shinhee_assets")[0]["one_child_bonus_percent"] == 10
    assert of(result, "shinhee_assets")[0]["child_relaxation_since"] == "2023-03-28"
