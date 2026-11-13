from datetime import date

import pytest

from app.extract.official_rules import parse_official_rules
from app.extract.reviewed_sources import reviewed_applyhome_mirror


def applyhome_url(number):
    return f"https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo={number}&pblancNo={number}"


@pytest.mark.parametrize(("number", "cutoff", "file_id"), [
    ("2026000531", "2026-10-23", "69171330"),
    ("2026000533", "2026-10-30", "69296327"),
    ("2026820015", "2026-11-06", "69314535"),
    ("2026820013", "2026-10-30", "69223600"),
])
def test_lh_mirror_requires_the_current_applyhome_notice_number_and_date(number, cutoff, file_id):
    url = applyhome_url(number)
    mirror = reviewed_applyhome_mirror(url, date.fromisoformat(cutoff))
    assert mirror is not None
    assert mirror[0] == f"https://apply.lh.or.kr/lhapply/lhFile.do?fileid={file_id}"
    assert reviewed_applyhome_mirror(url, None) is None
    assert reviewed_applyhome_mirror(url, "2026-11-13") is None
    assert reviewed_applyhome_mirror(url.replace(f"pblancNo={number}", "pblancNo=2026000532"), cutoff) is None
    assert reviewed_applyhome_mirror(url + f"&houseManageNo={number}", cutoff) is None
    assert reviewed_applyhome_mirror(url.replace("www.applyhome.co.kr", "example.com"), cutoff) is None
    assert reviewed_applyhome_mirror(url.replace("selectAPTLttotPblancDetail.do", "getAtchmnfl.do"), cutoff) is None


def test_reviewed_lh_correction_uses_original_cutoff_only_for_exact_attachment():
    url, digest = reviewed_applyhome_mirror(applyhome_url("2026000531"), "2026-10-23")
    pages = [{"page": 1, "text": (
        "시흥거모지구 S-1블록 공공분양주택 입주자모집공고\n"
        "이 주택의 입주자모집공고일은 2026.10.23.이며 주택관리번호는 2026000531입니다.\n"
        "금회 공급되는 주택은 「주택법」에 의한 국민주택입니다.\n"
    )}]
    payload = {"official_url": (
        "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do?"
        "panId=0000061195&ccrCnntSysDsCd=02&uppAisTpCd=05&aisTpCd=05&mi=1027"
    ), "title": "[정정공고]시흥거모 S-1블록 공공분양주택 입주자모집공고",
        "category": "public_sale", "announcement_date": "2026-10-27"}
    corrected = parse_official_rules(pages, url=url, digest=digest, payload=payload)
    context = next(rule["value"] for rule in corrected["rules"] if rule["kind"] == "qualification_context")
    assert context["application_criterion_date"] == "2026-10-23"
    assert context.get("correction_publication_date") is None
    assert payload["announcement_date"] == "2026-10-27"
    for changed_url, changed_digest, changed_payload in [
        (url, "0" * 64, payload),
        (url.replace("69171330", "69296327"), digest, payload),
        (url, digest, {**payload, "official_url": payload["official_url"].replace("0000061195", "0000061186")}),
        (url, digest, {**payload, "announcement_date": "2026-10-28"}),
    ]:
        rejected = parse_official_rules(pages, url=changed_url, digest=changed_digest, payload=changed_payload)
        assert rejected["identity_status"] == "mismatch"
        assert rejected["rules"] == []
