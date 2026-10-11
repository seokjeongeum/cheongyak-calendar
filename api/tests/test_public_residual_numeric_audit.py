"""A broad source quotation cannot certify an unmodeled numeric predicate."""
import copy
import json
from pathlib import Path

import pytest

from app.extract.official_rules import parse_official_rules
from app.qualification import requirements_complete


SOURCE = json.loads((Path(__file__).parent / "fixtures/gajeong-admission-v8.json").read_text())


def parse(pages, *, future=False):
    payload = copy.deepcopy(SOURCE["payload"])
    digest, url = SOURCE["document_hash"], SOURCE["document_url"]
    if future:
        for page in pages:
            page["text"] = page["text"].replace("인천가정2", "새로운공공단지").replace("2026.09.23", "2027.10.11").replace("2026.04.15", "2027.02.03")
            page["page"] += 70
        payload.update(title="새로운공공단지 공공분양 잔여세대 추가 입주자모집공고",
                       external_id="0000099999", announcement_date="2027-10-11",
                       official_url="https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do?panId=0000099999")
        digest, url = "unseen-corrected-document", "https://apply.lh.or.kr/lhapply/lhFile.do?fileid=99999999"
    return parse_official_rules(pages, url=url, digest=digest, payload=payload)


@pytest.mark.parametrize("future", [False, True])
def test_supported_full_residual_source_remains_complete_for_a_new_identity_and_page_position(future):
    result = parse(copy.deepcopy(SOURCE["pages"]), future=future)
    assert result["status"] == "complete"
    assert requirements_complete(result["rules"], False)


@pytest.mark.parametrize("future", [False, True])
@pytest.mark.parametrize("subject", ["자동차가액 4,500만원 이하", "특정직종 근무기간 19년 이상"])
def test_numeric_gate_inside_domestic_residence_quote_remains_an_explicit_source_gap(future, subject):
    pages = copy.deepcopy(SOURCE["pages"])
    replaced = 0
    for page in pages:
        old = "국내에 거주하는 만 19세 이상의 성년자"
        replaced += page["text"].count(old)
        page["text"] = page["text"].replace(old, f"국내에 거주하고 {subject}인 신청자 중 만 19세 이상의 성년자")
    assert replaced > 0
    result = parse(pages, future=future)
    # The quoted domestic fact remains useful; its extra numeric subject has
    # no implemented rule and must not inherit the fact's verified status.
    domestic = next(rule for rule in result["rules"] if rule["kind"] == "domestic_residence")
    assert subject in domestic["evidence_text"]
    assert result["status"] == "partial"
    assert not requirements_complete(result["rules"], False)
    coverage = next(rule for rule in result["rules"] if rule["kind"] == "condition_coverage")
    scope = coverage["scopes"][0]
    assert scope["complete"] is False
    assert any(gap["stage"] == "clause_extraction" and subject in gap.get("evidence_text", "")
               for gap in scope["source_gaps"])
    assert scope["reviewed_document_hash"] == ("unseen-corrected-document" if future else SOURCE["document_hash"])
