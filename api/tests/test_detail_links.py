"""New public notices resolve without a curated project/id mapping."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from app.db import init_db, make_engine
from app.ingest import detail_links as links
from app.repository import notice_public, upsert_notice

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def payload(**changes):
    return {"source": "cheongyak_home", "external_id": "new-public-notice", "title": "새로운별빛 리버파크 2단지(2회차)",
            "category": "apt", "address": "경기도 누리시 하늘동 123-4번지 일원", "announcement_date": "2026-10-10",
            "official_url": "https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=2026000999&pblancNo=2026000999",
            "price_cap_status": "unknown", "rules": [{"kind": "housing_classification", "effect": "metadata", "housing_kind": "private"}],
            **changes}


def candidate(**changes):
    return {"id": "newXYZ", "name": "새로운별빛리버파크2단지", "address": "경기도 누리시 하늘동 123-4", "type": 0,
            "baseinfo": {"applyHomeInfo": {"houseManageNo": 2026000999, "pblancNo": 2026000999}}, **changes}


def html(state):
    return '<html><script id="__HGNN_DATA__" type="application/json">' + json.dumps({"altState": state}, ensure_ascii=False) + '</script></html>'


def transport(rows, details, calls):
    def handler(request):
        calls.append(str(request.url))
        if request.url.path == "/search":
            return httpx.Response(200, text=html({"SearchStore": {"searchResults": {"apt": {"list": rows}}}}))
        value = details.get(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, text=html({"AptStore": {"detail": value}}))
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def empty_memory_cache():
    links._CACHE.clear()
    yield
    links._CACHE.clear()


@pytest.mark.asyncio
async def test_unseen_new_project_gets_verified_detail_not_search_link():
    calls, original = [], payload()
    async with httpx.AsyncClient(transport=transport([candidate()], {"newXYZ": candidate()}, calls)) as client:
        result = await links.enrich_detail_link(original, client=client, now=NOW)
    assert links.public_detail_link(original, result["rules"]) == "https://hogangnono.com/apt/newXYZ"
    assert len(calls) == 2
    assert result["rules"][0] == original["rules"][0]
    assert len(original["rules"]) == 1
    evidence = result["rules"][-1]
    assert evidence["match_basis"] == "official_announcement_identity"
    assert evidence["verification"] == "external_verified"
    assert "search" not in evidence["url"]


@pytest.mark.asyncio
async def test_officetel_disambiguates_same_brand_same_parcel_apartment():
    office = candidate(id="office3", name="새로운별빛리버파크(오)", type=1)
    apartment = candidate(id="apt345", name="새로운별빛리버파크", type=0)
    original, calls = payload(title="새로운별빛 리버파크 오피스텔", category="officetel"), []
    async with httpx.AsyncClient(transport=transport([apartment, office], {"office3": office}, calls)) as client:
        result = await links.enrich_detail_link(original, client=client, now=NOW)
    assert links.public_detail_link(original, result["rules"]) == "https://hogangnono.com/apt/office3"
    assert not any("apt345" in url for url in calls)


@pytest.mark.asyncio
async def test_name_address_match_can_resolve_public_housing_without_applyhome_number():
    original = payload(source="lh", title="새로운별빛 리버파크 2단지 일반공급 잔여세대 (선착순) 입주자 모집공고",
                       category="public_sale", official_url="https://apply.lh.or.kr/public-notice?id=56789")
    public, calls = candidate(baseinfo={}), []
    async with httpx.AsyncClient(transport=transport([public], {"newXYZ": public}, calls)) as client:
        result = await links.enrich_detail_link(original, client=client, now=NOW)
    assert links.public_detail_link(original, result["rules"]) == "https://hogangnono.com/apt/newXYZ"
    assert result["rules"][-1]["match_basis"] == "name_category_address"


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"name": "새로운별빛리버파크1단지"}, {"name": "새로운별빛리버파크"},
    {"address": "경기도 다른시 하늘동 123-4"}, {"address": "경기도 누리시 하늘동 123-40"}, {"type": 1},
])
async def test_wrong_phase_address_or_type_never_becomes_link(changes):
    wrong, original, calls = candidate(baseinfo={}, **changes), payload(official_url=None), []
    async with httpx.AsyncClient(transport=transport([wrong], {"newXYZ": wrong}, calls)) as client:
        result = await links.enrich_detail_link(original, client=client, now=NOW)
    assert links.public_detail_link(original, result["rules"]) is None


@pytest.mark.asyncio
async def test_two_matching_provider_details_are_ambiguous():
    first, second = candidate(id="one123"), candidate(id="two456")
    original, calls = payload(), []
    async with httpx.AsyncClient(transport=transport([first, second], {"one123": first, "two456": second}, calls)) as client:
        result = await links.enrich_detail_link(original, client=client, now=NOW)
    assert links.public_detail_link(original, result["rules"]) is None
    assert result["rules"][-1]["status"] == "ambiguous_identity"


@pytest.mark.asyncio
async def test_search_hint_without_real_detail_identity_is_not_published():
    calls = []
    async with httpx.AsyncClient(transport=transport([candidate()], {"newXYZ": {"id": "wrong123"}}, calls)) as client:
        result = await links.enrich_detail_link(payload(), client=client, now=NOW)
    assert links.public_detail_link(payload(), result["rules"]) is None


@pytest.mark.asyncio
async def test_positive_cache_survives_restart_and_metadata_reparse_without_http():
    calls, original = [], payload()
    async with httpx.AsyncClient(transport=transport([candidate()], {"newXYZ": candidate()}, calls)) as client:
        resolved = await links.enrich_detail_link(original, client=client, now=NOW)
    links._CACHE.clear()
    def unexpected(request):
        pytest.fail("Persisted fresh link must not call provider")
    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        result = await links.enrich_detail_link(original, client=client, previous_rules=resolved["rules"], now=NOW + timedelta(days=1))
    assert links.public_detail_link(original, result["rules"]) == "https://hogangnono.com/apt/newXYZ"


@pytest.mark.asyncio
async def test_negative_cache_bounds_retries_and_changed_identity_rechecks():
    calls, original = [], payload()
    async with httpx.AsyncClient(transport=transport([], {}, calls)) as client:
        failed = await links.enrich_detail_link(original, client=client, now=NOW)
        await links.enrich_detail_link(original, client=client, previous_rules=failed["rules"], now=NOW + timedelta(hours=3))
        await links.enrich_detail_link(payload(address="경기도 누리시 하늘동 555"), client=client, previous_rules=failed["rules"], now=NOW)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_provider_failure_never_blocks_a_notice_or_exposes_search():
    def unavailable(request):
        return httpx.Response(503, text="Temporarily unavailable")
    async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as client:
        result = await links.enrich_detail_link(payload(), client=client, now=NOW)
    assert result["title"] == payload()["title"]
    assert result["rules"][-1]["status"] == "provider_unavailable"
    assert links.public_detail_link(result, result["rules"]) is None


@pytest.mark.asyncio
async def test_unbounded_search_candidates_are_not_fetched():
    rows, calls = [candidate(id=f"abc{i}") for i in range(10)], []
    async with httpx.AsyncClient(transport=transport(rows, {}, calls)) as client:
        result = await links.enrich_detail_link(payload(), client=client, now=NOW)
    assert len(calls) == 1
    assert result["rules"][-1]["status"] == "ambiguous_search_results"


@pytest.mark.asyncio
async def test_unsafe_candidate_id_and_detail_urls_are_rejected():
    calls = []
    async with httpx.AsyncClient(transport=transport([candidate(id="../search?q=anything")], {}, calls)) as client:
        result = await links.enrich_detail_link(payload(), client=client, now=NOW)
    assert len(calls) == 1
    assert links.public_detail_link(payload(), result["rules"]) is None


@pytest.mark.asyncio
async def test_repository_list_detail_project_cache_and_preserve_history(tmp_path):
    calls = []
    async with httpx.AsyncClient(transport=transport([candidate()], {"newXYZ": candidate()}, calls)) as client:
        resolved = await links.enrich_detail_link(payload(), client=client, now=NOW)
    engine = make_engine(f"sqlite:///{tmp_path / 'links.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        notice = upsert_notice(session, resolved)
        session.commit()
        assert notice_public([notice]).hogangnono_url == "https://hogangnono.com/apt/newXYZ"
        assert notice_public([notice], detail=True).hogangnono_url == "https://hogangnono.com/apt/newXYZ"
        notice = upsert_notice(session, payload(rules=payload()["rules"]))
        session.commit()
        assert notice_public([notice]).hogangnono_url == "https://hogangnono.com/apt/newXYZ"
        changed = upsert_notice(session, payload(title="새로운별빛 리버파크 1단지", rules=payload()["rules"]))
        session.commit()
        assert notice_public([changed]).hogangnono_url is None
    engine.dispose()


@pytest.mark.asyncio
async def test_cached_proof_cannot_be_reused_as_search_or_other_complex():
    calls = []
    async with httpx.AsyncClient(transport=transport([candidate()], {"newXYZ": candidate()}, calls)) as client:
        resolved = await links.enrich_detail_link(payload(), client=client, now=NOW)
    proof = copy.deepcopy(resolved["rules"][-1])
    proof["url"] = "https://hogangnono.com/search?q=anything"
    assert links.public_detail_link(payload(), [proof]) is None
    assert links.public_detail_link(payload(category="officetel"), resolved["rules"]) is None
    assert links.public_detail_link(payload(address="경기도 누리시 하늘동 999"), resolved["rules"]) is None


@pytest.mark.asyncio
async def test_transient_provider_failure_retries_at_next_three_hour_cycle():
    calls = []
    def unavailable(request):
        calls.append(str(request.url))
        return httpx.Response(503)
    async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as client:
        result = await links.enrich_detail_link(payload(), client=client, now=NOW)
        await links.enrich_detail_link(payload(), client=client, previous_rules=result["rules"], now=NOW + timedelta(hours=2))
        assert len(calls) == 1
        await links.enrich_detail_link(payload(), client=client, previous_rules=result["rules"], now=NOW + timedelta(hours=3))
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [{"SearchStore": None}, {"SearchStore": {"searchResults": "changed"}},
                                    {"SearchStore": {"searchResults": {"apt": []}}}])
async def test_provider_structure_changes_do_not_block_public_notices(state):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html(state)))) as client:
        result = await links.enrich_detail_link(payload(), client=client, now=NOW)
    assert result["title"] == payload()["title"]
    assert links.public_detail_link(payload(), result["rules"]) is None


@pytest.mark.asyncio
async def test_shared_city_but_different_district_cannot_confirm_same_local_name():
    original = payload(address="서울특별시 송파구 별빛동 123-4", official_url=None)
    wrong = candidate(address="서울특별시 강동구 별빛동 123-4", baseinfo={})
    async with httpx.AsyncClient(transport=transport([wrong], {"newXYZ": wrong}, [])) as client:
        result = await links.enrich_detail_link(original, client=client, now=NOW)
    assert links.public_detail_link(original, result["rules"]) is None


@pytest.mark.asyncio
async def test_api_category_correction_keeps_matching_apartment_provider_identity():
    async with httpx.AsyncClient(transport=transport([candidate()], {"newXYZ": candidate()}, [])) as client:
        result = await links.enrich_detail_link(payload(), client=client, now=NOW)
    assert links.public_detail_link(payload(category="private_rental"), result["rules"]) == "https://hogangnono.com/apt/newXYZ"


@pytest.mark.asyncio
async def test_generic_ampersand_normalization_still_requires_official_identity():
    original = payload(title="새로운별빛앤리버파크2단지")
    provider = candidate(name="새로운별빛&리버파크2단지", address="경기도 누리시 하늘동 123-5")
    async with httpx.AsyncClient(transport=transport([provider], {"newXYZ": provider}, [])) as client:
        result = await links.enrich_detail_link(original, client=client, now=NOW)
    assert links.public_detail_link(original, result["rules"]) == "https://hogangnono.com/apt/newXYZ"
    assert result["rules"][-1]["match_basis"] == "official_announcement_identity"


@pytest.mark.asyncio
async def test_actual_public_provider_shape_resolves_office_without_project_map():
    from pathlib import Path
    recorded = json.loads((Path(__file__).parent / "fixtures" / "hogangnono_public_identity.json").read_text())
    original = payload(title="더샵 오산역아크시티 오피스텔", category="officetel", address="경기도 오산시 가수동 453번지 (오산 세교2지구 M1블록)",
                       official_url="https://www.applyhome.co.kr/ai/aia/selectPRMOLttotPblancDetailView.do?houseManageNo=2026950086&pblancNo=2026950086&houseSecd=02")
    public = recorded["detail"]
    async with httpx.AsyncClient(transport=transport(recorded["search_candidates"], {public["id"]: public}, [])) as client:
        result = await links.enrich_detail_link(original, client=client, now=NOW)
    assert links.public_detail_link(original, result["rules"]) == recorded["public_detail_url"]


@pytest.mark.asyncio
async def test_in_memory_discovery_cache_has_bounded_size(monkeypatch):
    monkeypatch.setattr(links, "_MAX_CACHE", 2)
    async with httpx.AsyncClient(transport=transport([], {}, [])) as client:
        for number in range(3):
            await links.enrich_detail_link(payload(title=f"새로운공고{number}"), client=client, now=NOW)
    assert len(links._CACHE) == 2


@pytest.mark.asyncio
async def test_same_district_name_in_different_cities_cannot_confirm_identity():
    original = payload(address="서울특별시 중구 별빛동 123-4", official_url=None)
    wrong = candidate(address="대구광역시 중구 별빛동 123-4", baseinfo={})
    async with httpx.AsyncClient(transport=transport([wrong], {"newXYZ": wrong}, [])) as client:
        result = await links.enrich_detail_link(original, client=client, now=NOW)
    assert links.public_detail_link(original, result["rules"]) is None


@pytest.mark.asyncio
async def test_address_spacing_variation_is_generic_not_project_alias():
    original = payload(address="경기도 누리시 하늘동123-4번지 일원", official_url=None)
    public = candidate(baseinfo={})
    async with httpx.AsyncClient(transport=transport([public], {"newXYZ": public}, [])) as client:
        result = await links.enrich_detail_link(original, client=client, now=NOW)
    assert links.public_detail_link(original, result["rules"]) == "https://hogangnono.com/apt/newXYZ"


@pytest.mark.asyncio
async def test_unicode_roman_phase_normalizes_but_different_phase_is_rejected():
    original = payload(title="새로운별빛 디에트르Ⅱ", official_url=None)
    public = candidate(name="새로운별빛디에트르II", baseinfo={})
    async with httpx.AsyncClient(transport=transport([public], {"newXYZ": public}, [])) as client:
        result = await links.enrich_detail_link(original, client=client, now=NOW)
    assert links.public_detail_link(original, result["rules"]) == "https://hogangnono.com/apt/newXYZ"
    assert links.public_detail_link(payload(title="새로운별빛 디에트르Ⅰ", official_url=None), result["rules"]) is None


@pytest.mark.asyncio
async def test_even_official_id_cannot_hide_explicit_wrong_numbered_phase():
    wrong = candidate(name="새로운별빛리버파크1단지")
    async with httpx.AsyncClient(transport=transport([wrong], {"newXYZ": wrong}, [])) as client:
        result = await links.enrich_detail_link(payload(), client=client, now=NOW)
    assert links.public_detail_link(payload(), result["rules"]) is None
