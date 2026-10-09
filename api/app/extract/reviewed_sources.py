"""Reviewed official cross-links where Applyhome points only to an LH index.

These are public source identities, not applicant data or inferred housing
types. A changed file is reparsed, never supplied old conditions by URL alone.
The hashes/validation pages are recorded for reproducible source comparison.
"""

from urllib.parse import parse_qs, urlparse

from .current_regional_sources import CURRENT_REGIONAL_SOURCES

UNRANKED_RESTRICTIONS = [
    {"restriction": "prior_project_contract", "scope": "applicant", "label": "이 단지의 기존 계약·추가입주자 선정",
     "pattern": r"동\s*주택에\s*당첨되어\s*계약을\s*체결한\s*분\s*또는\s*예비입주자\s*중\s*추가입주자로\s*선정된\s*분"},
    {"restriction": "prior_project_winner", "scope": "applicant", "label": "이 단지의 기존 당첨",
     "pattern": r"동\s*주택에\s*당첨되었으나\s*계약을\s*체결하지\s*않은\s*분"},
    {"restriction": "ineligible_restriction_active", "scope": "applicant", "label": "부적격 당첨으로 입주자 선정 제한",
     "pattern": r"부적격\s*당첨자로서\s*그\s*제한기간\s*중에\s*있는\s*분"},
    {"restriction": "resale_restriction_active", "scope": "applicant", "label": "공급질서 교란·전매 위반으로 청약 제한",
     "pattern": r"공급질서교란자로서\s*그\s*제한기간\s*중에\s*있는\s*분"},
]

REVIEWED_SOURCES = {
    "2026910249": {
        "title": "세종 우미 린 센터파크 무순위(사후)", "announcement_date": "2026-10-01", "housing_kind": "private",
        "document_url": "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026910249&pblancNo=2026910249&atchmnflSeqNo=1988068&atchmnflSn=3",
        "document_hash": "77bb487853d5002ecc64590d7466c3672b8d8149e9a50359d912d607a09b7959",
        "reviewed_pages": [1, 2, 3, 6],
        "unranked_review": {"qualification_page": 6, "adult_law": True, "original_project_id": "2026000323",
            "required_kinds": ["residence_region", "homeless", "citizenship", "any", "overseas_residence", "application_restriction"],
            "restrictions": UNRANKED_RESTRICTIONS},
    },
    "2026910250": {
        "title": "신림스카이아파트 무순위(사후)", "announcement_date": "2026-10-01", "housing_kind": "private",
        "document_url": "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026910250&pblancNo=2026910250&atchmnflSeqNo=1978039&atchmnflSn=2",
        "document_hash": "81b9eb927a5fb657db5158a3cfe78fc8ad8322a3e9e52b0af4c0596afbd4343f",
        "reviewed_pages": [1, 2, 3, 5],
        "unranked_review": {"qualification_page": 5, "adult_law": True, "original_project_id": "2021000515",
            "required_kinds": ["residence_region", "homeless", "citizenship", "any", "overseas_residence", "application_restriction"],
            "restrictions": [*UNRANKED_RESTRICTIONS,
                {"restriction": "rewinning_restriction_active", "scope": "household", "label": "본인·확인 대상 세대원의 재당첨 제한",
                 "pattern": r"과거\s*재당첨\s*제한\s*대상\s*주택에\s*당첨되어\s*현재\s*그\s*기간\s*중에\s*있는\s*분\s*및\s*그\s*세대원"}]},
    },
    "2026930040": {
        "title": "강변역 센트럴 아이파크 불법행위재공급", "announcement_date": "2026-09-23", "housing_kind": "private",
        "document_url": "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026930040&pblancNo=2026930040&atchmnflSeqNo=1982993&atchmnflSn=5",
        "document_hash": "97987f527a961051724f6561aca34451e3131a23ae9e11a0c65ee53ddee1d98e",
        "reviewed_pages": [1, 2, 3, 6],
        "unranked_review": {"qualification_page": 6, "original_project_id": "2024000226",
            "required_kinds": ["residence_region", "homeless", "household_head", "citizenship", "any", "overseas_residence", "application_restriction"],
            "restrictions": [
                {"restriction": "ineligible_restriction_active", "scope": "applicant", "label": "부적격 당첨으로 입주자 선정 제한",
                 "pattern": r"제58조제3항에\s*따른\s*입주자선정\s*제한기간\s*중에\s*있는\s*분\s*\(부적격\s*당첨자\)"},
                {"restriction": "resale_restriction_active", "scope": "applicant", "label": "공급질서 교란·전매 위반으로 청약 제한",
                 "pattern": r"제56조제1항에\s*따른\s*입주자자격\s*제한기간\s*중에\s*있는\s*분\s*\(공급질서교란자\s*또는\s*전매제한\s*위반자\)"},
                {"restriction": "rewinning_restriction_active", "scope": "applicant_spouse", "label": "본인·배우자의 재당첨 제한",
                 "pattern": r"기존\s*주\s*택\s*당첨으로\s*인해\s*재당첨\s*제한\s*기간\s*내에\s*있는\s*분\s*및\s*그\s*배우자는[^■]{0,100}?청약이\s*불가"}]},
    },
    "2026000494": {
        "title": "더샵 동인센트리체",
        "announcement_date": "2026-10-02",
        "document_url": "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026000494&pblancNo=2026000494&atchmnflSeqNo=1988347&atchmnflSn=2",
        "document_hash": "21bacace8ce7d1ce942a42c22e4c34547becb286c3bfa1ac5862b9be7f861acb",
        "reviewed_pages": [5, 6, 12, 13, 14, 16, 17, 20, 22, 23],
        "rank_reviewed_pages": [22, 23],
        "rank_required_kinds": ["account_type", "private_rank_months", "deposit_min_krw"],
        "regions": [{"region_code": "27", "region_name": "대구광역시"}, {"region_code": "47", "region_name": "경상북도"}],
        "region_page": 5,
        "local_priority": {"region_code": "27", "region_name": "대구광역시", "min_months": 0},
        "military_exception": {"kind": "military_service_years", "min_years": 10, "currently_serving": True, "residence_area": "local"},
    },
    "2026000414": {
        "title": "인천계양 A6블록 공공분양",
        "announcement_date": "2026-08-31",
        "source_page_url": "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do?panId=0000061174&ccrCnntSysDsCd=02&uppAisTpCd=05&aisTpCd=05&mi=1027",
        "document_url": "https://apply.lh.or.kr/lhapply/lhFile.do?fileid=68595376",
        "document_hash": "d6c05d1d85013d523387d55bffcc6cc721a7c88d140883ae9de7c168b6287dd5",
        "reviewed_pages": [1, 2, 3, 22, 24, 25, 26, 27, 28, 29, 30],
        "rank_reviewed_pages": [2, 29],
        "rank_required_kinds": ["account_type", "national_rank_months", "recognized_payments_min"],
    },
    "2026820010": {
        "title": "인천계양 A17블록 신혼희망타운",
        "announcement_date": "2026-09-30",
        "source_page_url": "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do?panId=0000061179&ccrCnntSysDsCd=02&uppAisTpCd=39&aisTpCd=39&mi=1027",
        "document_url": "https://apply.lh.or.kr/lhapply/lhFile.do?fileid=68807314",
        "document_hash": "f591455563e503427c61699da3823b2029aa8ba24e3d09d84478ce01686d10e0",
        "reviewed_pages": [1, 2, 14, 15, 16],
    },
    "2026000453": {
        "title": "광명 시티프라디움 에듀하임",
        "announcement_date": "2026-09-18",
        "document_url": "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026000453&pblancNo=2026000453&atchmnflSeqNo=1971127&atchmnflSn=7",
        "document_hash": "e4b9cd987e63bc4e2d4e33f74b616492a051aaafb90ca59053329edf05d0c693",
        "reviewed_pages": [1, 6, 25, 26],
        "rank_reviewed_pages": [25],
        "rank_required_kinds": ["account_type", "private_rank_months", "deposit_min_krw", "household_head", "ownership_count_max", "previous_winning"],
        "regions": [{"region_code": "41", "region_name": "경기도"}, {"region_code": "11", "region_name": "서울특별시"}, {"region_code": "28", "region_name": "인천광역시"}],
        "region_page": 25,
        "local_priority": {"region_code": "41210", "region_name": "경기도 광명시", "min_months": 24},
        "allocation_page": 26,
        "allocation_method": "all_local_first",
    },
    "2026950085": {
        "title": "잠실에떼르넬비욘드",
        "announcement_date": "2026-09-30",
        "document_url": "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026950085&pblancNo=2026950085&atchmnflSeqNo=1977178&atchmnflSn=3",
        "document_hash": "89c9ed1aac831abe2b7e2958eb00a780ecb5387672603c8a118c4e2d34eb9436",
        "reviewed_pages": [1, 2, 3, 4, 5],
        "rank_applicability": "not_applicable",
        "account_required": False,
        "sale_prices": [{"unit_type": "28D", "area_sqm": 28.43, "amount_krw": 588000000}, {"unit_type": "36A", "area_sqm": 35.81, "amount_krw": 819800000}, {"unit_type": "40B", "area_sqm": 39.23, "amount_krw": 913810000}, {"unit_type": "40C", "area_sqm": 39.94, "amount_krw": 937560000}],
        "application_fee_krw": 3000000,
    },
}


# Supply-table columns and regional priority reviewed against these exact files.
REVIEWED_SOURCES.update({'2026910251': {'title': '충정로역자이르네', 'announcement_date': '2026-09-28', 'housing_kind': 'private', 'reviewed_pages': [1, 2, 3, 4, 8], 'regional_review': True, 'region_page': 2, 'regions': [{'region_code': '11', 'region_name': '서울특별시'}], 'priority_applicable': False, 'inventory_page': 4, 'inventory_columns': ['일반공급'], 'inventory_units': {'084.9972A': [21], '084.9965B': [14]}, 'price_cap_status': 'no', 'price_cap_page': 3, 'adult_law': True, 'document_url': 'https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026910251&pblancNo=2026910251&atchmnflSeqNo=1986036&atchmnflSn=2', 'document_hash': '8fa5641c86777a48b65638f8036fc3bf6b53f0a4969b6c494fff88deb2ae7cd6'}, '2026930038': {'title': '고양 장항 아테라', 'announcement_date': '2026-10-02', 'housing_kind': 'private', 'reviewed_pages': [1, 2, 3, 4, 5, 10, 11, 12], 'regional_review': True, 'region_page': 3, 'regions': [{'region_code': '41280', 'region_name': '경기도 고양시'}], 'priority_applicable': False, 'inventory_page': 5, 'inventory_columns': ['노부모부양 특별공급', '일반공급'], 'inventory_units': {'084.9958A': [3, 1], '084.9478B': [1, 1]}, 'price_cap_status': 'yes', 'price_cap_page': 4, 'document_url': 'https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026930038&pblancNo=2026930038&atchmnflSeqNo=1990056&atchmnflSn=4', 'document_hash': '6b5b9d90c9a111e276ce85c19ce6ac021c4a9b5ce222b37fa49698e48a1330f7'}, '2026930039': {'title': '탕정 푸르지오 리버파크', 'announcement_date': '2026-10-02', 'housing_kind': 'private', 'reviewed_pages': [1, 2, 3, 4, 6, 7, 8], 'regional_review': True, 'region_page': 3, 'regions': [{'region_code': '44200', 'region_name': '충청남도 아산시'}], 'priority_applicable': False, 'military_exception': {'min_years': 10, 'currently_serving': True, 'residence_area': 'local'}, 'military_page': 4, 'inventory_page': 4, 'inventory_columns': ['생애최초 특별공급'], 'inventory_units': {'059.9901A': [2], '074.8177A': [1]}, 'price_cap_status': 'yes', 'price_cap_page': 4, 'document_url': 'https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026930039&pblancNo=2026930039&atchmnflSeqNo=1988277&atchmnflSn=3', 'document_hash': 'b2d655bace2f889a1905488fdd2f7900f525d781961797f0e2480746ba1d100a'}, '2026000444': {'title': '제주시 이도이동 아이린8차 아파트', 'announcement_date': '2026-10-02', 'housing_kind': 'private', 'reviewed_pages': [3, 4, 5, 6, 8], 'regional_review': True, 'region_page': 4, 'regions': [{'region_code': '50', 'region_name': '제주특별자치도'}], 'local_priority': {'region_code': '50', 'region_name': '제주특별자치도', 'min_months': 12}, 'priority_applicable': True, 'military_exception': {'min_years': 10, 'currently_serving': True, 'residence_area': 'other'}, 'military_page': 5, 'inventory_page': 6, 'inventory_columns': ['일반공급'], 'inventory_units': {'084.4900A': [9], '084.1200B': [9], '084.1100C': [9], '084.4800D': [9], '084.1200E': [9]}, 'rank_required_kinds': ['account_type', 'private_rank_months', 'deposit_min_krw'], 'rank_reviewed_pages': [8], 'document_url': 'https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026000444&pblancNo=2026000444&atchmnflSeqNo=1988268&atchmnflSn=1', 'document_hash': '834e6d70710e7bbfc03d420600fa88d9ee11b79933dd47dd72797255342822bd'}, '2026000498': {'title': '천안 아이파크 시티 2단지(2회차)', 'announcement_date': '2026-10-02', 'housing_kind': 'private', 'reviewed_pages': [4, 5, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21, 22], 'regional_review': True, 'region_page': 4, 'regions': [{'region_code': '44', 'region_name': '충청남도'}, {'region_code': '30', 'region_name': '대전광역시'}, {'region_code': '36', 'region_name': '세종특별자치시'}], 'local_priority': {'region_code': '44130', 'region_name': '충청남도 천안시', 'min_months': 0}, 'priority_applicable': True, 'military_exception': {'min_years': 10, 'currently_serving': True, 'residence_area': 'local'}, 'military_page': 5, 'inventory_page': 5, 'inventory_columns': ['기관추천 특별공급', '다자녀가구 특별공급', '신혼부부 특별공급', '노부모부양 특별공급', '생애최초 특별공급', '신생아 특별공급', '일반공급'], 'inventory_units': {'084.9800A': [4, 4, 5, 1, 3, 4, 16], '084.9700B': [2, 2, 4, 1, 1, 2, 12]}, 'rank_required_kinds': ['account_type', 'private_rank_months', 'deposit_min_krw'], 'rank_reviewed_pages': [22], 'document_url': 'https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026000498&pblancNo=2026000498&atchmnflSeqNo=1991055&atchmnflSn=1', 'document_hash': 'dd62febed115a2ed2c457820e9aa9fcb10df93b4c017764f36b6d1273f23400d'}})

REVIEWED_SOURCES["2026000444"]["rank_reviewed_pages"] = [9]

def reviewed_document_url(official_url: str) -> str | None:
    parsed = urlparse(official_url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.applyhome.co.kr", "applyhome.co.kr"}:
        return None
    params = parse_qs(parsed.query)
    number = (params.get("houseManageNo") or [""])[0]
    if (params.get("pblancNo") or [""])[0] != number:
        return None
    return {**REVIEWED_SOURCES, **CURRENT_REGIONAL_SOURCES}.get(number, {}).get("document_url")


def reviewed_document_urls(official_url: str, *, announcement_date: str | None = None) -> list[str]:
    """Fallbacks retain the current official notice number and reviewed date.

    A project-hosted corrected copy is an independent source with its own
    reviewed hash. It is never substituted for a different notice or date.
    The parser still verifies the downloaded document's identity and bytes.
    """
    primary = reviewed_document_url(official_url)
    if not primary:
        return []
    number = parse_qs(urlparse(official_url).query)["houseManageNo"][0]
    sources = [source for key, source in {**REVIEWED_SOURCES, **CURRENT_REGIONAL_SOURCES}.items()
               if key == number or key.startswith(number + "-")]
    if announcement_date:
        sources = [source for source in sources if source.get("announcement_date") == str(announcement_date)[:10]]
    return list(dict.fromkeys(source["document_url"] for source in sources))


def reviewed_source_for_document(url: str, digest: str) -> dict | None:
    """Recognize the same hash-bound Applyhome attachment on its www host."""
    parsed = urlparse(url)
    for source in {**REVIEWED_SOURCES, **CURRENT_REGIONAL_SOURCES}.values():
        if source.get("document_hash") != digest:
            continue
        reviewed = urlparse(source["document_url"])
        if url == source["document_url"]:
            return source
        if (parsed.scheme == reviewed.scheme == "https"
                and parsed.hostname == "www.applyhome.co.kr"
                and reviewed.hostname == "static.applyhome.co.kr"
                and parsed.path == reviewed.path == "/ai/aia/getAtchmnfl.do"
                and parsed.query == reviewed.query and not parsed.fragment):
            return source
    return None

# Exclusive areas are columns checked in each reviewed supply table.
for _review in REVIEWED_SOURCES.values():
    if _review.get("regional_review"):
        _review["exclusive_areas"] = {unit: float(__import__("re").match(r"[0-9.]+", unit)[0]) for unit in _review["inventory_units"]}

REVIEWED_SOURCES["2026000444"]["adult_or_minor_page"] = 4
REVIEWED_SOURCES["2026000498"]["adult_or_minor_page"] = 22

# Remaining current private-sale documents: regional qualification paragraphs
# and the positive cells of the supply table, checked against exact PDF bytes.
_capital = [{"region_code": "41", "region_name": "경기도"}, {"region_code": "11", "region_name": "서울특별시"}, {"region_code": "28", "region_name": "인천광역시"}]
_columns = ["기관추천 특별공급", "다자녀가구 특별공급", "신혼부부 특별공급", "노부모부양 특별공급", "생애최초 특별공급", "신생아 특별공급", "일반공급"]
REVIEWED_SOURCES.update({
    "2026000468": {
        "title": "쌍용 더 플래티넘 한강", "announcement_date": "2026-10-02",
        "document_url": "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026000468&pblancNo=2026000468&atchmnflSeqNo=1990183&atchmnflSn=2",
        "document_hash": "90a4d4e7e50b205ae45ee27cd7b3b50b5b8e1b3a65f19580f156336308cc1c34",
        "regional_review": True, "region_page": 4, "regions": _capital,
        "local_priority": {"region_code": "41830", "region_name": "경기도 양평군", "min_months": 0}, "priority_applicable": True,
        "military_page": 4, "military_exception": {"min_years": 10, "currently_serving": True, "residence_area": "other"},
        "inventory_page": 5, "inventory_columns": _columns,
        "inventory_units": {"074.9845": [7,7,10,2,5,7,32], "084.9947A": [15,14,22,4,10,15,69], "084.8542B": [4,4,6,1,3,4,18], "084.8894C": [3,4,6,1,2,3,18], "123.7781": [0,4,0,1,0,0,30], "146.8598P": [0,0,0,0,0,0,2]},
        "adult_or_minor_page": 4,
    },
    "2026000386": {
        "title": "용인 양지 서희스타힐스 하이뷰", "announcement_date": "2026-10-02",
        "document_url": "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026000386&pblancNo=2026000386&atchmnflSeqNo=1961129&atchmnflSn=6",
        "document_hash": "b08df1475867c4c75e2d7f3d2d94e63be338975dc9ae5578638aa8dc9e56cf96",
        "regional_review": True, "region_page": 4, "regions": _capital,
        "local_priority": {"region_code": "41460", "region_name": "경기도 용인시", "min_months": 0}, "priority_applicable": True,
        "military_page": 4, "military_exception": {"min_years": 10, "currently_serving": True, "residence_area": "other"},
        "inventory_page": 6, "inventory_columns": _columns,
        "inventory_units": {"059.9671A": [1,1,2,0,1,1,7], "059.9960B": [1,1,1,0,0,1,2], "059.9759C": [1,1,1,0,0,1,3], "069.9865A": [1,1,2,0,1,1,5], "074.9936A": [0,0,0,0,0,0,3], "074.9980B": [0,0,1,0,0,0,3], "084.9999A": [0,0,0,0,0,0,3], "084.9989B": [0,0,0,0,0,0,1]},
        "adult_or_minor_page": 4,
    },
    "2026000463": {
        "title": "향남역 그로브 스위첸", "announcement_date": "2026-10-02",
        "document_url": "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026000463&pblancNo=2026000463&atchmnflSeqNo=1978209&atchmnflSn=5",
        "document_hash": "718d3a166be758bb8e4cae0617741b52c4d372050dcb399e5f8874583dafce01",
        "regional_review": True, "region_page": 5, "regions": _capital,
        "local_priority": {"region_code": "41590", "region_name": "경기도 화성시", "min_months": 0}, "priority_applicable": True,
        "military_page": 5, "military_exception": {"min_years": 10, "currently_serving": True, "residence_area": "other"},
        "inventory_page": 7, "inventory_columns": _columns,
        "inventory_units": {"071.8178": [5,5,8,1,4,5,21], "084.9592A": [38,38,56,11,26,38,164], "084.9767B": [14,14,21,4,10,14,61], "084.9221C": [14,14,21,4,10,14,61], "084.9140D": [13,13,19,4,9,13,54], "107.9722A": [0,6,0,2,0,0,50], "107.8263B": [0,5,0,2,0,0,45], "147.9931P": [0,0,0,0,0,0,2]},
        "adult_or_minor_page": 5,
    },
    "2026910253": {
        "title": "오남역 서희스타힐스 여의재 1단지", "announcement_date": "2026-10-01", "housing_kind": "private",
        "document_url": "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026910253&pblancNo=2026910253&atchmnflSeqNo=1988120&atchmnflSn=3",
        "document_hash": "ec488adf1e0259c2b9e705abcbea025e06ffdc9158b95e5cef2e5c3d8adfdac3",
        "reviewed_pages": [1,2,3,7],
        "unranked_inventory": {"page":4,"units":{"084.9596":12}},
        "unranked_review": {"qualification_page": 7, "adult_law": True, "original_project_id": "2026000365",
            "required_kinds": ["domestic_residence", "homeless", "citizenship", "any", "overseas_residence", "application_restriction"],
            "restrictions": UNRANKED_RESTRICTIONS},
    },
})
for _review in REVIEWED_SOURCES.values():
    if _review.get("regional_review"):
        _review.setdefault("exclusive_areas", {unit: float(__import__("re").match(r"[0-9.]+", unit)[0]) for unit in _review["inventory_units"]})

REVIEWED_SOURCES["2026910251"].update({
    "reviewed_pages": [1,2,3,4,12], "admission_sections_reviewed": True, "remaining_admission_topics": [],
    "unranked_review": {"qualification_page":12,"adult_law":True,"original_project_id":"2026000358",
        "overseas_reviewed_page":2,
        "required_kinds":["residence_region","homeless","citizenship","any","overseas_residence","application_restriction"],
        "restrictions":[*UNRANKED_RESTRICTIONS,
            {"restriction":"rewinning_restriction_active","scope":"household","label":"본인·확인 대상 세대원의 재당첨 제한",
             "pattern":r"과거\s*재당첨\s*제한\s*대상\s*주택에\s*당첨되어\s*현재\s*그\s*기간\s*중에\s*있는\s*분\s*및\s*그\s*세대원"}]},
})

# The project publishes this exact corrected file separately from 청약홈.
# Both identities retain their own hash; a correction never borrows a review
# from the old PDF merely because its project number is the same.
REVIEWED_SOURCES["2026000463-project-pdf"] = {
    **REVIEWED_SOURCES["2026000463"],
    "document_url": "https://xn--q20b245acmc65au2puno.com/data/gongo_re.pdf",
    "document_hash": "b5668bcd00f9606b110b21c9703fdce3994f5f690b43299fadeaf9ed2a73c61e",
    "inventory_page": 8,
    "military_page": 6,
}

REVIEWED_SOURCES.update({
    "2026950087": {
        "title": "당산역 더클래스 한강", "announcement_date": "2026-10-06",
        "document_url": "https://www.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026950087&pblancNo=2026950087&atchmnflSeqNo=1988261&atchmnflSn=4",
        "document_hash": "99df9ab26e35d6af38b68c4d39f3d2d9b830460c232d77d725868a31dfda9804",
        "reviewed_pages": list(range(1, 12)),
        "office_review": {"qualification_page": 4, "adult_age": 19, "domestic_only": True},
    },
    "2026930033": {
        "title": "도안 푸르지오 디아델 29블록", "announcement_date": "2026-10-06", "housing_kind": "private",
        "document_url": "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026930033&pblancNo=2026930033&atchmnflSeqNo=1988251&atchmnflSn=2",
        "document_hash": "c6e98d471653081d934654fbfa5f0094356822659e626517e7a5991a1df705c6",
        "regional_review": True, "region_page": 4, "regions": [{"region_code": "30", "region_name": "대전광역시"}],
        "priority_applicable": False, "military_page": 4,
        "military_exception": {"min_years": 10, "currently_serving": True, "residence_area": "local"},
        "inventory_page": 5, "inventory_columns": ["노부모부양 특별공급", "일반공급"],
        "inventory_units": {"106.9500A": [1, 0], "124.0000": [0, 2]},
        "exclusive_areas": {"106.9500A": 106.95, "124.0000": 124.98}, "adult_or_minor_page": 4,
        "remaining_admission_topics": ["노부모부양 출산특례의 1회 사용·기존주택 처분 조건", "공급질서 교란·부적격 당첨의 적용 대상과 제한기간"],
        "remaining_admission_topics_by_supply": {
            "노부모부양 특별공급": ["노부모부양 출산특례의 1회 사용·기존주택 처분 조건", "공급질서 교란·부적격 당첨의 적용 대상과 제한기간"],
            "일반공급": ["공급질서 교란·부적격 당첨의 적용 대상과 제한기간"],
        },
    },
    "2026910256": {
        "title": "상동역 롯데캐슬 시그니처", "announcement_date": "2026-10-06", "housing_kind": "private",
        "document_url": "https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026910256&pblancNo=2026910256&atchmnflSeqNo=1991039&atchmnflSn=2",
        "document_hash": "8c4d8a5c9f46e7ec5c73439ffc4f008d592f60c12f6a99242f477ee1063387bc",
        "reviewed_pages": [1, 2, 3, 4, 5, 8],
        "unranked_review": {"qualification_page": 8, "adult_law": True, "original_project_id": "2026000354",
            "required_kinds": ["homeless", "citizenship", "any", "overseas_residence", "application_restriction"],
            "restrictions": UNRANKED_RESTRICTIONS},
        "unranked_inventory": {"page": 3, "units": {"084.9199A": 112, "084.7123B": 45, "084.9874C": 267}},
    },
})
