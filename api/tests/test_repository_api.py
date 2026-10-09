from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import get_session, init_db, make_engine
from app.main import app
from app.models import Notice, NoticeRevision
from app.extract.official_rules import PARSER_VERSION
from app.repository import record_source_status, resolve_pending_corrections, upsert_notice


@pytest.fixture()
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'notices.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


@pytest.fixture()
def client(db):
    def override_session():
        yield db

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def example_notice(source="cheongyak_home", external_id="A-100"):
    return {
        "source": source,
        "external_id": external_id,
        "provider": "한국부동산원",
        "title": "서울 햇살 아파트 입주자모집공고",
        "category": "apt",
        "address": "서울특별시 강남구 역삼동 100",
        "region_code": "11680",
        "region_name": "서울특별시 강남구",
        "announcement_date": "2026-09-28",
        "official_url": "https://example.go.kr/notice/A-100",
        "price_cap_status": "yes",
        "events": [
            {"kind": "special", "label": "특별공급", "start_date": "2026-10-06", "end_date": "2026-10-06", "audience": "해당지역"},
            {"kind": "first_priority", "label": "1순위", "start_date": "2026-10-07", "end_date": "2026-10-08", "audience": "해당지역"},
        ],
        "prices": [
            {"unit_type": "59A", "area_sqm": 59.98, "price_kind": "sale_max", "amount_krw": 934000000, "basis_label": "주택형별 최고 분양금액", "verification": "official", "evidence_url": "https://example.go.kr/notice/A-100"},
            {"unit_type": "84A", "area_sqm": 84.98, "price_kind": "sale_max", "amount_krw": 1245000000, "basis_label": "주택형별 최고 분양금액", "verification": "official", "evidence_url": "https://example.go.kr/notice/A-100"},
        ],
        "rules": [
            {"kind": "residence_months", "operator": ">=", "value": 24, "verification": "official", "evidence_url": "https://example.go.kr/notice/A-100"}
        ],
        "rules_complete": False,
    }


def test_all_unit_prices_and_cap_filter_are_visible_without_detail_click(db, client):
    notice = upsert_notice(db, example_notice())
    db.commit()

    response = client.get("/api/notices", params={"start": "2026-10-01", "end": "2026-10-31", "cap_only": "true"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    card = data["items"][0]
    assert card["id"] == notice.id
    assert card["price_cap_status"] == "yes"
    assert [price["unit_type"] for price in card["prices"]] == ["59A", "84A"]
    assert card["prices"][1]["amount_krw"] == 1245000000
    assert card["prices"][1]["source"] == "cheongyak_home"
    assert len(card["events"]) == 2
    assert card["rules_complete"] is False

    assert client.get("/api/notices", params={"start": "2026-11-01", "end": "2026-11-30"}).json()["total"] == 0
    assert client.get("/api/notices", params={"start": "2026-10-31", "end": "2026-10-01"}).status_code == 422


def classification(kind="private", *, verification="official"):
    return {"kind": "housing_classification", "effect": "metadata", "housing_kind": kind,
            "verification": verification, "source": "cheongyak_home",
            "evidence_url": "https://www.data.go.kr/data/15098547/openapi.do",
            "evidence_text": "HOUSE_DTL_SECD=01 (민영)"}


def qualification_context(**values):
    return {"kind": "qualification_context", "effect": "metadata", "value": values,
            "verification": "official", "source": "cheongyak_home",
            "evidence_url": "https://www.data.go.kr/data/15098547/openapi.do"}


def test_existing_database_notices_remain_unchanged_and_unknown(db, client):
    raw = example_notice()
    notice = upsert_notice(db, raw)
    db.commit()
    before = (notice.id, notice.version, notice.content_hash, len(notice.prices), len(notice.revisions))
    card = client.get("/api/notices").json()["items"][0]
    detail = client.get(f"/api/notices/{notice.id}").json()
    for item in (card, detail):
        assert item["housing_kind"] == "unknown"
        assert item["housing_kind_evidence"] is None
        assert all(value is None for value in item["qualification_context"].values())
        assert len(item["prices"]) == 2
    assert before == (notice.id, notice.version, notice.content_hash, len(notice.prices), len(notice.revisions))
    # Classification is stored in existing JSON, so no migration/drop/recreate
    # of the populated notice/price/competition tables is needed.
    from sqlalchemy import inspect
    assert "housing_kind" not in {column["name"] for column in inspect(db.bind).get_columns("notices")}


def test_list_and_detail_project_official_classification_and_nullable_context(db, client):
    raw = example_notice()
    raw["rules"] = [classification("national"), qualification_context(capital_region=True, speculation_zone=False,
                        subscription_overheated=True, public_housing=None)]
    raw["rules_complete"] = True  # Metadata alone must never certify eligibility.
    notice = upsert_notice(db, raw)
    db.commit()
    for item in (client.get("/api/notices").json()["items"][0], client.get(f"/api/notices/{notice.id}").json()):
        assert item["housing_kind"] == "national"
        assert item["housing_kind_evidence"]["verification"] == "official"
        assert item["housing_kind_evidence"]["evidence_url"].startswith("https://www.data.go.kr")
        assert item["qualification_context"] == {"public_housing": None, "speculation_zone": False,
                   "subscription_overheated": True, "weakened_area": None, "capital_region": True, "rule_effective_date": None, "original_announcement_date": None,
                   "application_announcement_date": None, "application_criterion_date": None, "application_criterion_basis": None}
        assert item["rules_complete"] is False


def test_provider_and_unverified_classification_do_not_prove_housing_kind(db, client):
    raw = example_notice(source="lh")
    raw.update(provider="LH", category="public_sale", rules=[classification("national", verification="ai_unverified")])
    notice = upsert_notice(db, raw)
    db.commit()
    data = client.get(f"/api/notices/{notice.id}").json()
    assert data["housing_kind"] == "unknown"
    assert data["housing_kind_evidence"]["verification"] == "unknown"


def test_conflicting_duplicate_classification_and_context_are_unknown(db, client):
    a = example_notice()
    a["rules"] += [classification("private"), qualification_context(speculation_zone=True, capital_region=True)]
    first = upsert_notice(db, a)
    b = example_notice(source="myhome", external_id="SAME-COPY")
    b["rules"] += [classification("national"), qualification_context(speculation_zone=False, capital_region=True)]
    second = upsert_notice(db, b)
    db.commit()
    assert second.duplicate_of_id == first.id
    data = client.get(f"/api/notices/{first.id}").json()
    assert data["housing_kind"] == "unknown"
    assert "서로 달라" in data["housing_kind_evidence"]["evidence_text"]
    assert data["qualification_context"]["speculation_zone"] is None
    assert data["qualification_context"]["capital_region"] is True


def test_metadata_only_source_poll_preserves_conditions_ai_candidates_and_original_date(db, client):
    raw = example_notice()
    raw["rules"] += [{"kind": "unparsed", "verification": "ai_unverified", "text": "공개 문서 후보"}]
    first = upsert_notice(db, raw)
    upsert_notice(db, {"source": raw["source"], "external_id": raw["external_id"], "announcement_date": "2026-10-02",
                      "rules": [classification(), qualification_context(original_announcement_date="2026-10-02", capital_region=True)]})
    db.commit()
    data = client.get(f"/api/notices/{first.id}").json()
    assert data["housing_kind"] == "private"
    assert {rule["kind"] for rule in data["rules"]} == {"residence_months", "unparsed", "housing_classification", "qualification_context"}
    assert len(data["prices"]) == 2
    context = next(rule for rule in data["rules"] if rule["kind"] == "qualification_context")
    assert context["value"]["original_announcement_date"] == "2026-09-28"
    version = data["version"]
    upsert_notice(db, {"source": raw["source"], "external_id": raw["external_id"],
                      "rules": [classification(), qualification_context(original_announcement_date="2026-10-02", capital_region=True)]})
    db.commit()
    assert first.version == version


def test_new_id_correction_keeps_original_qualification_date(db, client):
    original = example_notice(external_id="ORIGINAL-DATE")
    original["rules"] += [classification(), qualification_context(original_announcement_date="2026-09-28")]
    first = upsert_notice(db, original)
    corrected = {**original, "external_id": "CORRECTED-DATE", "announcement_date": "2026-10-03",
                 "correction_of_external_id": original["external_id"],
                 "rules": [classification(), qualification_context(original_announcement_date="2026-10-03")]}
    second = upsert_notice(db, corrected)
    db.commit()
    data = client.get(f"/api/notices/{second.id}").json()
    assert data["correction_of_id"] == first.id
    assert data["announcement_date"] == "2026-10-03"  # Official correction date stays intact.
    assert data["qualification_context"]["original_announcement_date"] == "2026-09-28"
    assert next(rule for rule in data["rules"] if rule["kind"] == "qualification_context")["value"]["original_announcement_date"] == "2026-09-28"


def test_metadata_is_separate_from_nested_condition_verification(db, client):
    raw = example_notice()
    raw["rules"] = [classification("unknown", verification="unknown"), {"kind": "all", "verification": "official", "conditions": [
        {"kind": "household_head", "verification": "official", "value": True},
        {"kind": "homeless", "verification": "official", "value": True}]}]
    raw["rules_complete"] = True
    first = upsert_notice(db, raw)
    assert first.rules_complete is True
    raw["rules"][1]["conditions"][1]["verification"] = "ai_unverified"
    upsert_notice(db, raw)
    db.commit()
    assert client.get(f"/api/notices/{first.id}").json()["rules_complete"] is False


def test_application_window_and_pagination_use_application_dates(db, client):
    december = example_notice(external_id="DEC")
    december["title"] = "12월 접수 공고"
    december["announcement_date"] = "2026-10-10"
    december["events"] = [
        {"kind": "general", "label": "청약 접수", "start_date": "2026-12-03", "end_date": "2026-12-05"},
        {"kind": "announcement", "label": "당첨자 발표", "start_date": "2026-12-15"},
    ]
    november = example_notice(external_id="NOV")
    november["title"] = "11월 접수 공고"
    november["announcement_date"] = "2026-10-20"
    november["events"] = [{"kind": "general", "label": "접수", "start_date": "2026-11-20"}]
    no_application = example_notice(external_id="NO-DATE")
    no_application["title"] = "접수일 미공개 공고"
    no_application["announcement_date"] = "2026-11-05"
    no_application["events"] = [{"kind": "announcement", "label": "당첨자 발표", "start_date": "2026-12-10"}]
    for row in (december, november, no_application):
        row["address"] += row["external_id"]
        upsert_notice(db, row)
    db.commit()

    november_cards = client.get("/api/notices", params={"start": "2026-11-01", "end": "2026-11-30"}).json()
    assert november_cards["total"] == 2
    assert [item["title"] for item in november_cards["items"]] == ["접수일 미공개 공고", "11월 접수 공고"]
    assert [item["sort_date"] for item in november_cards["items"]] == ["2026-11-05", "2026-11-20"]
    assert client.get("/api/notices", params={"start": "2026-11-21", "end": "2026-11-21"}).json()["total"] == 0
    assert client.get("/api/notices", params={"start": "2026-12-04", "end": "2026-12-04"}).json()["total"] == 1

    all_pages = [client.get("/api/notices", params={"page": page, "page_size": 1}).json()["items"][0] for page in (1, 2, 3)]
    assert [item["sort_date"] for item in all_pages] == ["2026-11-05", "2026-11-20", "2026-12-03"]


def test_application_only_and_rental_exclusion_filter_before_pagination(db, client):
    cases = (
        ("ACTIVE", "진행 중", "apt", [
            {"kind": "general", "label": "접수", "start_date": "2026-09-28", "end_date": "2026-10-02"},
        ]),
        ("NEXT", "다음 접수", "public_sale", [
            {"kind": "special", "label": "지난 접수", "start_date": "2026-09-20"},
            {"kind": "general", "label": "다음 접수", "start_date": "2026-10-03"},
        ]),
        ("PAST", "지난 접수만", "apt", [
            {"kind": "general", "label": "접수", "start_date": "2026-09-15"},
        ]),
        ("FUTURE", "범위 밖 접수", "apt", [
            {"kind": "general", "label": "접수", "start_date": "2026-10-08"},
        ]),
        ("NO-APP", "접수일 미공개", "apt", [
            {"kind": "announcement", "label": "공고", "start_date": "2026-10-01"},
        ]),
        ("RENT", "공공임대 접수", "public_rental", [
            {"kind": "general", "label": "접수", "start_date": "2026-10-01"},
        ]),
    )
    for external_id, title, category, events in cases:
        row = example_notice(external_id=external_id)
        row.update(title=title, category=category, announcement_date="2026-10-01", events=events,
                   address=f"서울특별시 강남구 {external_id}")
        upsert_notice(db, row)
    db.commit()

    params = {"start": "2026-09-30", "end": "2026-10-05", "application_only": "true",
              "exclude_public_rental": "true", "page_size": 1}
    first = client.get("/api/notices", params={**params, "page": 1}).json()
    second = client.get("/api/notices", params={**params, "page": 2}).json()
    third = client.get("/api/notices", params={**params, "page": 3}).json()
    assert [first["total"], second["total"], third["total"]] == [2, 2, 2]
    assert [first["items"][0]["title"], second["items"][0]["title"]] == ["진행 중", "다음 접수"]
    assert [first["items"][0]["sort_date"], second["items"][0]["sort_date"]] == ["2026-09-30", "2026-10-03"]
    assert first["items"][0]["events"][0]["start_date"] == "2026-09-28"
    assert [event["start_date"] for event in second["items"][0]["events"]] == ["2026-09-20", "2026-10-03"]
    assert third["items"] == []

    # Each flag is opt-in. The default still exposes notices lacking a known
    # reception date, while the application-only view includes public rental.
    assert client.get("/api/notices", params={"start": "2026-09-30", "end": "2026-10-05"}).json()["total"] == 4
    assert client.get("/api/notices", params={**params, "exclude_public_rental": "false"}).json()["total"] == 3
    assert client.get("/api/notices", params={"application_only": "true"}).json()["total"] == 5


def test_application_only_uses_merged_duplicate_reception(db, client):
    original = example_notice(external_id="MERGED-ROOT")
    original.update(title="합쳐진 모집공고", address="서울특별시 강남구 합침",
                    announcement_date="2026-10-01", events=[])
    canonical = upsert_notice(db, original)
    duplicate = example_notice(source="myhome", external_id="MERGED-COPY")
    duplicate.update(title=original["title"], address=original["address"],
                     announcement_date=original["announcement_date"],
                     events=[{"kind": "general", "label": "접수", "start_date": "2026-10-02"}])
    copy = upsert_notice(db, duplicate)
    db.commit()
    assert copy.duplicate_of_id == canonical.id

    response = client.get("/api/notices", params={"start": "2026-10-01", "end": "2026-10-03",
                                                   "application_only": "true"}).json()
    assert response["total"] == 1
    assert response["items"][0]["id"] == canonical.id
    assert response["items"][0]["sort_date"] == "2026-10-02"


def test_repeated_poll_enrichment_and_correction_history(db, client):
    raw = example_notice()
    first = upsert_notice(db, raw)
    db.commit()
    original_id = first.id
    assert first.version == 1

    repeated = upsert_notice(db, raw)
    db.commit()
    assert repeated.version == 1

    enriched = {
        "source": raw["source"], "external_id": raw["external_id"],
        "document_hash": "sha256-1",
        "prices": raw["prices"] + [{"unit_type": "101A", "price_kind": "sale_total", "amount_krw": 2200000000, "verification": "auto_unverified", "document_hash": "sha256-1", "evidence_text": "101A: 22억"}],
        "rules": raw["rules"] + [{"kind": "unparsed", "text": "기타 조건", "verification": "ai_unverified"}],
    }
    upsert_notice(db, enriched)
    db.commit()

    # Official feeds can omit structured prices/rules on subsequent polls.
    upsert_notice(db, {**raw, "prices": [], "rules": []})
    db.commit()
    db.expire_all()  # API requests ordinarily use a fresh database session.
    detail = client.get(f"/api/notices/{original_id}").json()
    assert detail["version"] == 2
    assert len(detail["prices"]) == 3
    assert any(price["unit_type"] == "101A" and price["verification"] == "ai_unverified" for price in detail["prices"])
    assert len(detail["revisions"]) == 2
    assert detail["rules_complete"] is False

    # A corrected document invalidates unverified candidates from the old PDF.
    upsert_notice(db, {"source": raw["source"], "external_id": raw["external_id"], "document_hash": "sha256-2"})
    db.commit()
    db.expire_all()
    detail = client.get(f"/api/notices/{original_id}").json()
    assert detail["version"] == 3
    assert len(detail["prices"]) == 2
    assert all(rule["verification"] == "official" for rule in detail["rules"])
    assert db.query(NoticeRevision).filter_by(notice_id=original_id).count() == 3


def test_long_lived_writer_refreshes_version_and_children_before_partial_enrichment(db):
    raw = example_notice(external_id="TWO-WRITERS")
    original = upsert_notice(db, raw)
    db.commit()
    factory = sessionmaker(bind=db.bind, expire_on_commit=False)
    with factory() as stale_writer, factory() as feed_writer:
        cached = stale_writer.get(Notice, original.id)
        old_event_ids = [event.id for event in cached.events]
        assert len(cached.prices) == 2
        stale_writer.commit()  # Keep the identity map, as the worker/CLI does.
        latest = {**raw, "title": "정정된 최신 제목", "events": [{"kind": "general", "label": "정정 접수", "start_date": "2026-10-15"}],
                  "prices": [{**raw["prices"][0], "amount_krw": 950000000}]}
        upsert_notice(feed_writer, latest)
        feed_writer.commit()
        assert cached.version == 1
        enriched = upsert_notice(stale_writer, {"source": raw["source"], "external_id": raw["external_id"],
                                               "document_hash": "fresh-document", "rules": [classification()]})
        stale_writer.commit()
        assert enriched is cached
        assert enriched.version == 3
        assert enriched.title == latest["title"]
        assert [event.label for event in enriched.events] == ["정정 접수"]
        assert len(enriched.prices) == 1 and enriched.prices[0].amount_krw == 950000000
        assert [event.id for event in enriched.events] != old_event_ids
        assert [revision.version for revision in stale_writer.query(NoticeRevision).filter_by(notice_id=original.id)
                .order_by(NoticeRevision.version)] == [1, 2, 3]


def test_rental_candidate_remains_single_price_after_next_source_poll(db, client):
    raw = example_notice(source="cheongyak_home", external_id="RENT-1")
    raw["category"] = "private_rental"
    raw["prices"] = [{"unit_type": "36A", "price_kind": "deposit", "amount_krw": None,
                      "monthly_krw": None, "verification": "unknown"}]
    notice = upsert_notice(db, raw)
    upsert_notice(db, {"source": raw["source"], "external_id": raw["external_id"],
                       "document_hash": "doc-1", "prices": [{"unit_type": "36A",
                       "price_kind": "deposit_monthly", "amount_krw": None,
                       "monthly_krw": 220000, "verification": "ai_unverified",
                       "document_hash": "doc-1", "evidence_text": "36A 월 22만원"}]})
    upsert_notice(db, raw)
    db.commit()
    prices = client.get(f"/api/notices/{notice.id}").json()["prices"]
    assert len(prices) == 1
    assert prices[0]["monthly_krw"] == 220000
    assert prices[0]["verification"] == "ai_unverified"


@pytest.mark.parametrize("change,carry_old_rules", [
    ({"document_hash": "unsupported-corrected-document"}, False),
    ({"document_hash": "unsupported-corrected-document"}, True),
    ({"official_url": "https://www.applyhome.co.kr/corrected-no-document"}, True),
])
def test_unreadable_corrected_document_drops_old_verified_parser_facts_but_keeps_history(db, client, change, carry_old_rules):
    raw = example_notice(external_id="OLD-PARSED-DOCUMENT")
    raw.update(document_hash="old-parsed-document", rules=[classification("private"),
        {"kind": "homeless", "value": True, "verification": "official", "source": "official_document_parser",
         "document_hash": "old-parsed-document", "evidence_text": "이전 공고의 무주택 조건"},
        {"kind": "condition_coverage", "effect": "metadata", "verification": "official", "source": "official_document_parser",
         "document_hash": "old-parsed-document", "scopes": [{"supply_type": "일반공급", "complete": True}]}])
    notice = upsert_notice(db, raw)
    db.commit()
    update = {"source": notice.source, "external_id": notice.external_id, **change}
    if carry_old_rules:
        update["rules"] = raw["rules"]
    upsert_notice(db, update)
    db.commit()
    result = client.get(f"/api/notices/{notice.id}").json()
    assert result["housing_kind"] == "private"  # Official API classification stays valid.
    assert not any(rule.get("source") == "official_document_parser" for rule in result["rules"])
    assert result["rules_complete"] is False
    versions = db.query(NoticeRevision).filter_by(notice_id=notice.id).order_by(NoticeRevision.version).all()
    assert len(versions) == 2
    assert any(rule.get("source") == "official_document_parser" for rule in versions[0].payload["rules"])


def test_corrected_document_keeps_only_parser_facts_matching_new_hash(db, client):
    raw = example_notice(external_id="PARSED-CORRECTION")
    old = {"kind": "homeless", "value": True, "verification": "official", "source": "official_document_parser",
           "document_hash": "old-doc", "parser_version": PARSER_VERSION, "evidence_text": "이전 공고 조건"}
    raw.update(document_hash="old-doc", rules=[classification(), old])
    notice = upsert_notice(db, raw)
    fresh = {**old, "value": False, "document_hash": "new-doc", "evidence_text": "정정 공고 조건"}
    upsert_notice(db, {"source": notice.source, "external_id": notice.external_id, "document_hash": "new-doc",
                       "rules": [classification(), old, fresh]})
    db.commit()
    rules = client.get(f"/api/notices/{notice.id}").json()["rules"]
    parsed = [rule for rule in rules if rule.get("source") == "official_document_parser"]
    assert len(parsed) == 1 and parsed[0]["document_hash"] == "new-doc" and parsed[0]["value"] is False


@pytest.mark.parametrize("failed_current", [False, True])
@pytest.mark.parametrize("legacy_version", ["official-sections-2026-10-03-v1", "official-sections-2026-10-04-v3"])
def test_partial_review_replaces_matching_compatible_rules_and_rejects_obsolete_versions(db, client, failed_current, legacy_version):
    current = {"source": "official_document_parser", "verification": "official",
               "parser_version": PARSER_VERSION, "document_hash": "same-official-file"}
    raw = example_notice(external_id="CURRENT-PARSER")
    raw.update(document_hash="same-official-file", rules_complete=False,
               rules=[classification("national"),
                      {**current, "kind": "housing_classification", "effect": "metadata", "housing_kind": "national"},
                      {**current, "kind": "qualification_context", "effect": "metadata",
                       "value": {"speculation_zone": False, "original_announcement_date": "2026-09-28"}},
                      {**current, "kind": "condition_coverage", "effect": "metadata",
                       "status": "unreadable" if failed_current else "partial",
                       "scopes": [{"supply_type": "일반공급", "complete": False}]}])
    if not failed_current:
        raw["rules"].append({**current, "kind": "homeless", "value": True, "supply_type": "일반공급"})
    canonical = upsert_notice(db, raw)
    old = {**current, "parser_version": legacy_version}
    duplicate_payload = {**raw, "source": "myhome", "external_id": "OBSOLETE-COPY", "rules_complete": True,
                         "rules": [{**old, "kind": "housing_classification", "effect": "metadata", "housing_kind": "private"},
                                   {**old, "kind": "qualification_context", "effect": "metadata",
                                    "value": {"speculation_zone": True, "original_announcement_date": "2026-08-01"}},
                                   {**old, "kind": "homeless", "value": False, "supply_type": "일반공급"},
                                   {**old, "kind": "national_rank_months", "value": 6, "purpose": "first_rank"}]}
    duplicate = upsert_notice(db, duplicate_payload)
    db.commit()
    assert duplicate.duplicate_of_id == canonical.id
    for endpoint in ("/api/notices", f"/api/notices/{canonical.id}", f"/api/notices/{duplicate.id}"):
        response = client.get(endpoint).json()
        public = response["items"][0] if "items" in response else response
        assert public["housing_kind"] == "national"
        assert public["qualification_context"]["speculation_zone"] is False
        assert public["qualification_context"]["original_announcement_date"] == "2026-09-28"
        document_rules = [rule for rule in public["rules"] if rule.get("source") == "official_document_parser"]
        assert {rule["parser_version"] for rule in document_rules} == ({PARSER_VERSION, legacy_version} if legacy_version.endswith("-v3") else {PARSER_VERSION})
        conditions = [rule for rule in document_rules if rule.get("effect") != "metadata"]
        assert len(conditions) == (2 if legacy_version.endswith("-v3") else 0 if failed_current else 1)
        assert any(rule["kind"] == "national_rank_months" for rule in conditions) is legacy_version.endswith("-v3")
        assert not any(rule["kind"] == "homeless" and rule["value"] is False for rule in conditions) or failed_current
        assert public["rules_complete"] is False
        assert len(public["prices"]) == 2 and len(public["events"]) == 2
    # Public filtering never rewrites the archived duplicate or its provenance.
    assert any(rule.get("parser_version") == legacy_version for rule in duplicate.rules)
    archived = db.query(NoticeRevision).filter_by(notice_id=duplicate.id).one()
    assert any(rule.get("parser_version") == legacy_version for rule in archived.payload["rules"])


def document_rule(kind, *, version="official-sections-2026-10-07-v9", digest="reviewed-file", **fields):
    return {"kind": kind, "source": "official_document_parser", "verification": "official",
            "parser_version": version, "document_hash": digest, **fields}


def test_failed_current_download_preserves_reviewed_admission_regions_and_visible_diagnostics(db, client):
    old = [document_rule("homeless", value=True, supply_type="일반공급"),
           document_rule("applicant_regions", effect="metadata", scope_complete=True, regions=[{"province_code": "11"}]),
           document_rule("condition_coverage", effect="metadata", status="complete",
                         scopes=[{"supply_type": "일반공급", "complete": True, "verified_rule_count": 1}])]
    diagnostic = document_rule("document_diagnostics", version=PARSER_VERSION, effect="metadata", status="unreadable",
                               diagnostics=[{"stage": "download", "code": "document_download_failed", "status": "error"}])
    raw = example_notice(external_id="FAILED-REVIEW-RETAINED")
    raw.update(document_hash="reviewed-file", rules_complete=True, rules=[classification(), *old, diagnostic])
    notice = upsert_notice(db, raw)
    db.commit()
    for endpoint in ("/api/notices", f"/api/notices/{notice.id}"):
        response = client.get(endpoint).json()
        public = response["items"][0] if "items" in response else response
        assert all(rule in public["rules"] for rule in old)
        assert diagnostic in public["rules"]
        assert public["rules_complete"] is True
        assert not any(item.get("code") == "document_read" for item in diagnostic["diagnostics"])


def test_geographic_only_current_review_preserves_older_same_hash_admission(db, client):
    admission = document_rule("homeless", value=True, supply_type="일반공급")
    old_region = document_rule("applicant_regions", effect="metadata", scope_complete=True, unrestricted=True)
    current_region = document_rule("applicant_regions", version=PARSER_VERSION, effect="metadata", scope_complete=True,
                                   regions=[{"province_code": "11", "district_code": "11680"}])
    coverage = document_rule("condition_coverage", version=PARSER_VERSION, effect="metadata", status="partial",
                             scopes=[{"supply_type": "일반공급", "complete": False, "verified_rule_count": 0}])
    raw = example_notice(external_id="GEOGRAPHY-REVIEW-RETAINED")
    raw.update(document_hash="reviewed-file", rules=[classification(), admission, old_region, current_region, coverage])
    notice = upsert_notice(db, raw)
    db.commit()
    public = client.get(f"/api/notices/{notice.id}").json()
    assert admission in public["rules"] and current_region in public["rules"]
    assert old_region not in public["rules"]
    assert public["rules_complete"] is False


def test_partial_current_review_replaces_conflicting_variants_only_in_same_scope(db, client):
    old = document_rule("homeless", value=True, supply_type="일반공급", unit_type="59A")
    conflict = {**old, "value": False}
    other_unit = {**old, "unit_type": "84A"}
    other_supply = {**old, "supply_type": "신혼부부"}
    fresh = document_rule("homeless", version=PARSER_VERSION, value=False, supply_types=["일반공급"], unit_types=["59A"])
    coverage = document_rule("condition_coverage", version=PARSER_VERSION, effect="metadata", status="partial",
                             scopes=[{"supply_type": "일반공급", "complete": False}])
    raw = example_notice(external_id="PARTIAL-SCOPED-REVIEW")
    raw.update(document_hash="reviewed-file", rules=[classification(), old, conflict, other_unit, other_supply, fresh, coverage])
    notice = upsert_notice(db, raw)
    db.commit()
    rules = client.get(f"/api/notices/{notice.id}").json()["rules"]
    assert old not in rules and conflict not in rules
    assert fresh in rules and other_unit in rules and other_supply in rules


def test_full_current_admission_review_retires_only_matching_scope(db, client):
    replaced = document_rule("age_min", value=19, supply_type="일반공급", unit_type="59A")
    other_unit = {**replaced, "unit_type": "84A"}
    other_supply = {**replaced, "supply_type": "신혼부부"}
    rank = document_rule("national_rank_months", value=6, purpose="first_rank", supply_type="일반공급", unit_type="59A")
    fresh = document_rule("homeless", version=PARSER_VERSION, value=True, supply_type="일반공급", unit_type="59A")
    coverage = document_rule("condition_coverage", version=PARSER_VERSION, effect="metadata", status="complete",
                             offered_supply_types=["일반공급"], scopes=[{"supply_type": "일반공급", "unit_type": "59A", "complete": True, "verified_rule_count": 1}])
    raw = example_notice(external_id="COMPLETE-SCOPED-REVIEW")
    raw.update(document_hash="reviewed-file", rules=[classification(), replaced, other_unit, other_supply, rank, fresh, coverage])
    notice = upsert_notice(db, raw)
    db.commit()
    rules = client.get(f"/api/notices/{notice.id}").json()["rules"]
    assert replaced not in rules
    assert all(rule in rules for rule in (other_unit, other_supply, rank, fresh))


def test_complete_general_review_does_not_retire_unreviewed_special_scope(db, client):
    global_old = document_rule("age_min", value=19)
    special_old = document_rule("age_min", value=19, supply_type="신혼부부")
    fresh = document_rule("homeless", version=PARSER_VERSION, value=True, supply_type="일반공급")
    coverage = document_rule("condition_coverage", version=PARSER_VERSION, effect="metadata", status="complete",
                             offered_supply_types=["일반공급"], scopes=[{"supply_type": "일반공급", "complete": True, "verified_rule_count": 1}])
    raw = example_notice(external_id="COMPLETE-GENERAL-SCOPE")
    raw.update(document_hash="reviewed-file", rules=[classification(), global_old, special_old, fresh, coverage])
    notice = upsert_notice(db, raw)
    db.commit()
    rules = client.get(f"/api/notices/{notice.id}").json()["rules"]
    assert global_old not in rules and special_old in rules


def test_geography_coverage_flag_alone_is_not_proof_of_new_admission_review(db, client):
    admission = document_rule("homeless", value=True, supply_type="일반공급")
    region = document_rule("applicant_regions", version=PARSER_VERSION, effect="metadata", scope_complete=True, unrestricted=True)
    coverage = document_rule("condition_coverage", version=PARSER_VERSION, effect="metadata", status="complete",
                             scopes=[{"supply_type": "일반공급", "complete": True, "verified_rule_count": 0}])
    raw = example_notice(external_id="GEOGRAPHY-NOT-ADMISSION-PROOF")
    raw.update(document_hash="reviewed-file", rules=[classification(), admission, region, coverage])
    notice = upsert_notice(db, raw)
    db.commit()
    rules = client.get(f"/api/notices/{notice.id}").json()["rules"]
    assert admission in rules


def test_nested_replacement_retires_whole_old_branch_without_weakening_it(db, client):
    branch = document_rule("all", label="함께 필요한 신청 조건", supply_type="일반공급", unit_type="59A",
                           conditions=[document_rule("homeless", value=True), document_rule("income_max", value=100)])
    other_unit = {**branch, "unit_type": "84A"}
    fresh = document_rule("homeless", version=PARSER_VERSION, value=False, supply_type="일반공급", unit_type="59A")
    raw = example_notice(external_id="NESTED-SCOPED-REVIEW")
    raw.update(document_hash="reviewed-file", rules=[classification(), branch, other_unit, fresh])
    notice = upsert_notice(db, raw)
    db.commit()
    rules = client.get(f"/api/notices/{notice.id}").json()["rules"]
    assert branch not in rules and other_unit in rules and fresh in rules
    assert not any(rule["kind"] == "income_max" for rule in rules)


def test_current_review_does_not_retire_valid_separate_provider_document(db, client):
    fresh = document_rule("homeless", version=PARSER_VERSION, digest="provider-a-file", value=True, supply_type="일반공급")
    raw = example_notice(external_id="PROVIDER-A-REVIEW")
    raw.update(document_hash="provider-a-file", rules=[classification(), fresh])
    notice = upsert_notice(db, raw)
    other = document_rule("homeless", digest="provider-b-file", value=False, supply_type="일반공급")
    duplicate = upsert_notice(db, {**raw, "source": "myhome", "external_id": "PROVIDER-B-REVIEW",
                                  "document_hash": "provider-b-file", "rules": [classification(), other]})
    db.commit()
    assert duplicate.duplicate_of_id == notice.id
    rules = client.get(f"/api/notices/{notice.id}").json()["rules"]
    assert fresh in rules and other in rules


def test_wrong_hash_current_rule_is_not_replacement_proof_and_never_leaks(db, client):
    retained = document_rule("homeless", value=True, supply_type="일반공급")
    wrong = document_rule("homeless", version=PARSER_VERSION, digest="different-file", value=False, supply_type="일반공급")
    raw = example_notice(external_id="WRONG-HASH-REVIEW")
    raw.update(document_hash="reviewed-file", rules=[classification(), retained, wrong])
    notice = upsert_notice(db, raw)
    db.commit()
    rules = client.get(f"/api/notices/{notice.id}").json()["rules"]
    assert retained in rules and wrong not in rules


@pytest.mark.asyncio
async def test_actual_hangang_v8_to_current_pipeline_and_duplicate_projection_roundtrip(db, client, monkeypatch):
    import json
    from pathlib import Path
    import httpx
    from app.extract import pipeline
    from app.extract.official_rules import parse_official_rules

    fixtures = Path(__file__).parent / "fixtures"
    source = next(row for row in json.loads((fixtures / "current-private-v5.json").read_text()) if row["external_id"] == "2026000468")
    prior = json.loads((fixtures / "hangang-prior-generic-v8.json").read_text())
    assert prior["document_hash"] == source["document_hash"]
    raw = {**source["payload"], "source": "cheongyak_home", "external_id": source["external_id"],
           "provider": "한국부동산원", "document_hash": source["document_hash"], "rules": [classification(), *prior["rules"]]}
    notice = upsert_notice(db, raw)
    duplicate = upsert_notice(db, {**raw, "source": "myhome", "external_id": "RECORDED-HANGANG-V8-COPY"})
    assert duplicate.duplicate_of_id == notice.id
    parsed = parse_official_rules(source["pages"], url=source["document_url"], digest=source["document_hash"], payload=source["payload"])

    async def extract(url, download_client, *, payload):
        return {**parsed, "document_url": source["document_url"], "document_hash": source["document_hash"],
                "diagnostics": [pipeline.document_diagnostic("decode", "document_read", source["document_url"], status="ok")]}

    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    html = f'<a href="{source["document_url"]}">모집공고문</a>'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html))) as download_client:
        enriched = await pipeline.enrich_notice(raw, download_client, known_document_hash=source["document_hash"], allow_gemini=False)
    upsert_notice(db, enriched)
    db.commit()
    old_special = [rule for rule in prior["rules"] if rule.get("supply_type")]
    assert len(old_special) == 8
    assert not any(rule in enriched["rules"] for rule in old_special)

    def general(rule):
        return (rule.get("effect") not in {"metadata", "priority"} and rule.get("purpose") != "first_rank"
                and rule.get("supply_type") in {None, "일반공급"}
                and (not rule.get("supply_types") or "일반공급" in rule["supply_types"]))

    expected_general = [rule for rule in parsed["rules"] if general(rule)]
    assert len(expected_general) == 8
    for endpoint in ("/api/notices", f"/api/notices/{notice.id}", f"/api/notices/{duplicate.id}"):
        response = client.get(endpoint).json()
        public = response["items"][0] if "items" in response else response
        assert [rule for rule in public["rules"] if general(rule)] == expected_general
        assert not any(rule in public["rules"] for rule in old_special)
        assert not any(rule["kind"] == "tax_years_min" for rule in public["rules"])
        first_rank = {rule["kind"]: rule for rule in public["rules"] if rule.get("purpose") == "first_rank"}
        assert {"private_rank_months", "deposit_min_krw", "account_type"} <= first_rank.keys()
        assert first_rank["private_rank_months"]["value"] == 12
        coverage = next(rule for rule in public["rules"] if rule["kind"] == "condition_coverage")
        scopes = {scope["supply_type"]: scope for scope in coverage["scopes"]}
        assert scopes["일반공급"]["complete"] is True
        assert {supply: scope["complete"] for supply, scope in scopes.items()} == {
            scope["supply_type"]: scope["complete"] for rule in parsed["rules"] if rule["kind"] == "condition_coverage" for scope in rule["scopes"]}
        assert scopes["신혼부부 특별공급"]["complete"] is False
        assert public["rules_complete"] is False
    # Projection does not rewrite the older duplicate's archived evidence.
    assert all(rule in duplicate.rules for rule in old_special)


@pytest.mark.parametrize("missing_proof", ["review_version", "reviewed_pages"])
def test_whole_source_admission_retirement_requires_registry_version_and_full_pages(db, client, missing_proof):
    import copy
    import json
    from pathlib import Path
    from app.extract.official_rules import parse_official_rules

    fixtures = Path(__file__).parent / "fixtures"
    source = next(row for row in json.loads((fixtures / "current-private-v5.json").read_text()) if row["external_id"] == "2026000468")
    prior = json.loads((fixtures / "hangang-prior-generic-v8.json").read_text())
    old_tax = next(rule for rule in prior["rules"] if rule["kind"] == "tax_years_min")
    parsed = parse_official_rules(source["pages"], url=source["document_url"], digest=source["document_hash"], payload=source["payload"])
    rules = copy.deepcopy(parsed["rules"])
    coverage = next(rule for rule in rules if rule["kind"] == "condition_coverage")
    coverage[missing_proof] = "unreviewed-version" if missing_proof == "review_version" else list(range(1, 62))
    for scope in coverage["scopes"]:
        scope[missing_proof] = "unreviewed-version" if missing_proof == "review_version" else list(range(1, 62))
        if scope["supply_type"] == "생애최초 특별공급":
            scope["complete"] = False
    raw = {**source["payload"], "source": "cheongyak_home", "external_id": source["external_id"],
           "provider": "한국부동산원", "document_hash": source["document_hash"], "rules": [*rules, old_tax]}
    notice = upsert_notice(db, raw)
    db.commit()
    assert old_tax in client.get(f"/api/notices/{notice.id}").json()["rules"]


@pytest.mark.parametrize("old_version", ["official-sections-2026-10-07-v9", PARSER_VERSION])
@pytest.mark.parametrize("failed_only", [False, True])
def test_latest_same_hash_diagnostics_replace_duplicate_failure_without_retiring_facts(db, client, old_version, failed_only):
    admission = document_rule("homeless", value=True, supply_type="일반공급")
    raw = example_notice(external_id="LATEST-SAME-HASH-DIAGNOSTICS")
    raw.update(document_hash="reviewed-file", rules=[classification(), admission])
    notice = upsert_notice(db, raw)
    previous = document_rule("document_diagnostics", version=old_version, effect="metadata", status="unreadable",
                             diagnostics=[{"stage": "discovery", "code": "announcement_download_failed", "status": "error"}])
    duplicate = upsert_notice(db, {**raw, "source": "myhome", "external_id": "OLD-DUPLICATE-DIAGNOSTICS",
                                  "rules": [classification(), admission, previous]})
    fresh = document_rule("document_diagnostics", version=PARSER_VERSION, effect="metadata", status="unreadable" if failed_only else "partial",
                          diagnostics=[{"stage": "download" if failed_only else "discovery",
                                        "code": "document_download_failed" if failed_only else "announcement_download_failed",
                                        "status": "error" if failed_only else "resolved"}])
    current_admission = admission if failed_only else {**admission, "parser_version": PARSER_VERSION}
    upsert_notice(db, {**raw, "rules": [classification(), current_admission, fresh], "replace_rules": True})
    db.commit()
    rules = client.get(f"/api/notices/{notice.id}").json()["rules"]
    assert fresh in rules and previous not in rules
    assert current_admission in rules
    if failed_only:
        assert admission in rules
    assert previous in duplicate.rules


@pytest.mark.parametrize("effect,purpose", [("priority", None), ("procedure", None), ("instruction", None), ("metadata", "selection")])
def test_non_admission_parent_children_cannot_replace_duplicate_admission_proof(db, client, effect, purpose):
    admission = document_rule("homeless", value=True, supply_type="일반공급")
    old_rank = document_rule("private_rank_months", value=6, purpose="first_rank")
    current_rank = {**old_rank, "value": 12, "parser_version": PARSER_VERSION}
    group = document_rule("all", version=PARSER_VERSION, effect=effect, purpose=purpose, supply_type="일반공급",
                          conditions=[document_rule("homeless", version=PARSER_VERSION, value=False)])
    coverage = document_rule("condition_coverage", version=PARSER_VERSION, effect="metadata", status="complete",
                             offered_supply_types=["일반공급"], scopes=[{"supply_type": "일반공급", "complete": True, "verified_rule_count": 1}])
    raw = example_notice(external_id="NON-ADMISSION-PROOF-BOUNDARY")
    raw.update(document_hash="reviewed-file", rules=[classification(), current_rank, group, coverage])
    notice = upsert_notice(db, raw)
    duplicate = upsert_notice(db, {**raw, "source": "myhome", "external_id": "PRIOR-ADMISSION-PROOF",
                                  "rules": [classification(), admission, old_rank]})
    db.commit()
    assert duplicate.duplicate_of_id == notice.id
    rules = client.get(f"/api/notices/{notice.id}").json()["rules"]
    assert admission in rules
    assert current_rank in rules and old_rank not in rules
    assert group in rules


def test_cross_source_duplicate_merges_complementary_prices_and_events(db, client):
    original = example_notice()
    a = upsert_notice(db, original)
    duplicate = example_notice(source="myhome", external_id="M-55")
    duplicate["prices"] = [{"unit_type": "101A", "price_kind": "sale_total", "amount_krw": 2200000000, "verification": "official"}]
    duplicate["events"] = [{"kind": "second_priority", "label": "2순위", "start_date": "2026-10-09"}]
    duplicate["official_url"] = "https://myhome.go.kr/notice/M-55"
    b = upsert_notice(db, duplicate)
    db.commit()

    assert b.duplicate_of_id == a.id
    cards = client.get("/api/notices", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    assert cards["total"] == 1
    assert cards["items"][0]["sources"] == ["cheongyak_home", "myhome"]
    assert {price["unit_type"] for price in cards["items"][0]["prices"]} == {"59A", "84A", "101A"}
    assert {price["unit_type"]: price["source"] for price in cards["items"][0]["prices"]}["101A"] == "myhome"
    assert len(cards["items"][0]["events"]) == 3
    assert client.get(f"/api/notices/{b.id}").json()["id"] == a.id


def test_new_external_id_correction_supersedes_old_schedule(db, client):
    original = example_notice()
    old = upsert_notice(db, original)
    secondary = example_notice(source="myhome", external_id="M-OLD")
    secondary["official_url"] = "https://myhome.go.kr/old"
    assert upsert_notice(db, secondary).duplicate_of_id == old.id
    correction = example_notice(external_id="A-101")
    correction["title"] = "서울 햇살 아파트 정정 입주자모집공고"
    correction["correction_of_external_id"] = "A-100"
    correction["events"] = [{"kind": "first_priority", "label": "1순위 정정", "start_date": "2026-10-10"}]
    new = upsert_notice(db, correction)
    db.commit()

    assert new.correction_of_id == old.id
    response = client.get("/api/notices", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    assert response["total"] == 1
    assert response["items"][0]["id"] == new.id
    assert response["items"][0]["correction_of_id"] == old.id
    assert response["items"][0]["events"][0]["start_date"] == "2026-10-10"


def test_myhome_bare_correction_id_resolves_only_unique_house_row(db):
    old = upsert_notice(db, example_notice(source="myhome", external_id="123:7"))
    correction = example_notice(source="myhome", external_id="124:7")
    correction["correction_of_external_id"] = "123"
    new = upsert_notice(db, correction)
    db.commit()
    assert new.correction_of_id == old.id


def test_correction_to_cross_source_duplicate_replaces_entire_old_group(db, client):
    original = example_notice(source="cheongyak_home", external_id="REB-1")
    old_root = upsert_notice(db, original)
    duplicate = example_notice(source="myhome", external_id="MY-1")
    duplicate["official_url"] = "https://myhome.go.kr/old"
    old_myhome = upsert_notice(db, duplicate)
    assert old_myhome.duplicate_of_id == old_root.id

    corrected = example_notice(source="myhome", external_id="MY-2")
    corrected["official_url"] = "https://myhome.go.kr/new"
    corrected["correction_of_external_id"] = "MY-1"
    corrected["events"] = [{"kind": "general", "label": "정정 접수", "start_date": "2026-10-11"}]
    corrected["prices"] = []
    new = upsert_notice(db, corrected)
    db.commit()

    assert new.correction_of_id == old_myhome.id
    assert new.duplicate_of_id is None
    page = client.get("/api/notices", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    assert page["total"] == 1
    assert page["items"][0]["id"] == new.id
    assert [event["start_date"] for event in page["items"][0]["events"]] == ["2026-10-11"]
    assert page["items"][0]["prices"] == []


def test_newest_first_correction_resolves_when_original_arrives_later(db, client):
    corrected = example_notice(source="sh", external_id="301479")
    corrected["title"] = "[정정] 마곡지구 입주자모집공고"
    corrected["correction_of_external_id"] = "301076"
    new = upsert_notice(db, corrected)
    assert new.correction_of_id is None

    original = example_notice(source="sh", external_id="301076")
    original["title"] = "마곡지구 입주자모집공고"
    old = upsert_notice(db, original)
    assert resolve_pending_corrections(db, "sh") == 1
    db.commit()
    assert new.correction_of_id == old.id
    page = client.get("/api/notices", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    assert page["total"] == 1
    assert page["items"][0]["id"] == new.id


def test_coverage_retains_last_success_and_api_has_no_profile_endpoint(db, client):
    now = datetime(2026, 9, 28, 9, tzinfo=timezone.utc)
    record_source_status(db, "lh", "ok", fetched_at=now, record_count=12)
    record_source_status(db, "lh", "error", message="upstream timeout", fetched_at=datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
    db.commit()

    response = client.get("/api/coverage")
    assert response.status_code == 200
    sources = {row["source"]: row for row in response.json()["sources"]}
    assert set(sources) >= {"cheongyak_home", "myhome", "lh", "ih", "sh", "gh"}
    assert sources["lh"]["status"] == "error"
    assert sources["lh"]["last_success_at"] is not None
    assert sources["lh"]["record_count"] == 12
    assert sources["ih"]["status"] == "pending"
    assert client.post("/api/profile", json={"address": "secret"}).status_code == 404
    assert not any("profile" in path for path in client.get("/api/openapi.json").json()["paths"])


@pytest.mark.parametrize("label", ["상시 접수", "마감 시까지", "소진\t시까지", "종료일 미공개"])
def test_explicit_open_reception_remains_visible_after_start_without_invented_end(db, client, label):
    raw = example_notice(external_id="OPEN")
    raw["events"] = [{"kind": "application", "label": label, "start_date": "2026-09-01", "end_date": None}]
    ongoing = upsert_notice(db, raw)
    dated_raw = example_notice(external_id="DATED")
    dated_raw["title"] = "기한 있는 접수"
    dated = upsert_notice(db, dated_raw)
    db.commit()

    response = client.get("/api/notices", params={"start": "2026-10-06", "end": "2026-11-30", "application_only": True})
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 2
    assert [item["id"] for item in page["items"]] == [dated.id, ongoing.id]
    assert page["items"][1]["events"][0]["end_date"] is None
    assert page["items"][1]["application_end_date"] is None
    assert page["items"][1]["sort_date"] is None
    assert client.get("/api/notices", params={"start": "2026-11-01", "end": "2026-11-30", "application_only": True}).json()["total"] == 1
    assert client.get("/api/notices", params={"start": "2026-08-01", "end": "2026-08-31", "application_only": True}).json()["total"] == 0


@pytest.mark.parametrize("label", ["1순위", "접수", "마감 안내 시 주의", "상시 계약일"])
def test_missing_end_without_explicit_ongoing_wording_stays_single_day(db, client, label):
    raw = example_notice(external_id="DAILY")
    raw["events"] = [{"kind": "application", "label": label, "start_date": "2026-09-01", "end_date": None}]
    upsert_notice(db, raw)
    db.commit()
    assert client.get("/api/notices", params={"start": "2026-10-06", "end": "2026-11-30", "application_only": True}).json()["total"] == 0
    past = client.get("/api/notices", params={"start": "2026-09-01", "end": "2026-09-01", "application_only": True}).json()
    assert past["total"] == 1
    assert past["items"][0]["application_end_date"] == "2026-09-01"
