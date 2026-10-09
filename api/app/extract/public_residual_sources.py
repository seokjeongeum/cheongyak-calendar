"""Current LH residual source identities, independent of neighboring offers."""
from urllib.parse import parse_qs, urlparse

GIMHAE_YANGSAN_HASH = "2a35a72f021c6e4f9bcf68f95e5d68a6bdaab0440135f473dbf1902a17558656"
GIMHAE_YANGSAN_DOCUMENT = "https://apply.lh.or.kr/lhapply/lhFile.do?fileid=68800694"
GIMHAE_YANGSAN_PAN_ID = "2015122300020860"
GIMHAE_YANGSAN_DATE = "2026-09-30"


def reviewed_public_residual_source(*, url, digest, payload):
    """The current detail page and attached fifteen-page PDF were compared.

    This September 30 Gimhae/Yangsan offer is separate from the July 6 LH
    Seonun 2 family offer and July 8 GMCC Seonun Dasaroum offer.
    """
    if digest != GIMHAE_YANGSAN_HASH or url != GIMHAE_YANGSAN_DOCUMENT:
        return None
    parsed = urlparse(str(payload.get("official_url") or ""))
    if parsed.scheme != "https" or parsed.hostname != "apply.lh.or.kr":
        return None
    if (parse_qs(parsed.query).get("panId") or [None])[0] != GIMHAE_YANGSAN_PAN_ID:
        return None
    if str(payload.get("announcement_date") or "")[:10] != GIMHAE_YANGSAN_DATE:
        return None
    return {
        "pages": list(range(1, 16)),
        "reviewed_section_pages": [1, 2, 9, 10, 11, 12, 13, 14, 15],
        "topics": ["age", "domestic_residence", "citizenship", "home_ownership", "application_restrictions"],
        "application_method": "unranked_after",
        "source_gaps_by_supply": {"일반공급": []},
        "branches": [
            {"branch_id": "adult", "label": "성년 신청자", "requirements": ["age", "domestic_residence", "citizenship", "home_ownership", "application_restrictions"]},
            {"branch_id": "minor_household_head", "label": "미성년 세대주", "requirements": ["공고의 자녀 또는 형제자매 부양 사유", "동일 등본의 미성년 자녀 또는 형제자매"]},
            {"branch_id": "ownership_exceptions", "label": "무주택 법령 예외", "requirements": ["제53조 주택·분양권 소유 예외의 실제 가족·취득·처분 사실"]},
        ],
        "restrictions": [
            {"restriction": "rewinning_restriction_active", "scope": "household", "page": 1,
             "label": "재당첨 제한 적용 세대 범위와 현재 제한기간",
             "pattern": r"재당첨\s*제한\s*대상\s*주택에\s*당첨된\s*자의\s*세대에\s*속하여\s*재당첨\s*제한\s*기간\s*중에\s*있는\s*분은\s*청약할\s*수\s*없습니다"},
            {"restriction": "ineligible_restriction_active", "scope": "applicant", "page": 1,
             "label": "부적격 당첨의 현재 입주자 선정 제한기간",
             "pattern": r"부적격\s*당첨자로\s*처리되어\s*당첨이\s*취소된\s*자는.{0,180}?입주자로\s*선정될\s*수\s*없는"},
        ],
    }
