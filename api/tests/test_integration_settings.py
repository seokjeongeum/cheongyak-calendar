import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import integration_settings as settings
from app.db import get_session, init_db, make_engine
from app.extract.pipeline import extraction_configured
from app.ingest.worker import _api_key
from app.main import app

TOKEN = "fictional-administrator-token"
KEY = "fictional-service-key"


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'settings.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(settings, "SessionLocal", factory)
    for name in settings.KEY_NAMES | {settings.CONFIRMATION}:
        monkeypatch.delenv(name, raising=False)
    def dependency():
        with factory() as session:
            yield session
    app.dependency_overrides[get_session] = dependency
    with factory() as session:
        settings.put_value(session, settings.ADMIN_HASH, hashlib.sha256(TOKEN.encode()).hexdigest())
        session.commit()
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def update(client, body):
    return client.put('/api/integrations', headers={"Authorization": f"Bearer {TOKEN}"}, json=body)


def test_save_reads_shared_worker_store_without_returning_keys(client):
    response = update(client, {"keys": {"LH_API_KEY": KEY}})
    assert response.status_code == 200
    assert KEY not in response.text and TOKEN not in response.text
    assert response.headers['cache-control'] == 'no-store'
    assert _api_key('lh') == KEY
    result = client.get('/api/integrations')
    assert KEY not in result.text
    assert next(s for s in result.json()['services'] if s['name'] == 'LH_API_KEY')['configured']


def test_public_visitors_and_wrong_admin_cannot_write(client):
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        response = client.put('/api/integrations', headers=headers, json={"keys": {"LH_API_KEY": KEY}})
        assert response.status_code == 401
        assert KEY not in response.text
    assert _api_key('lh') == ''


def test_delete_overrides_environment_and_shared_key_still_works(client, monkeypatch):
    monkeypatch.setenv('LH_API_KEY', 'old-environment-key')
    assert _api_key('lh') == 'old-environment-key'
    assert update(client, {"keys": {"LH_API_KEY": ''}}).status_code == 200
    assert _api_key('lh') == ''
    update(client, {"keys": {"DATA_GO_KR_API_KEY": 'common%2Bkey'}})
    assert _api_key('lh') == 'common+key'


def test_gemini_needs_explicit_confirmation_for_each_new_key(client):
    update(client, {"keys": {"GEMINI_API_KEY": KEY}})
    assert not extraction_configured()
    update(client, {"gemini_unbilled_confirmed": True})
    assert extraction_configured()
    update(client, {"keys": {"GEMINI_API_KEY": 'replacement-fictional-key'}})
    assert not extraction_configured()
    update(client, {"keys": {"GEMINI_API_KEY": ''}, "gemini_unbilled_confirmed": True})
    assert not extraction_configured()


def test_rejects_unknown_and_invalid_values_without_secret_echo(client):
    for body in ({"keys": {"unknown": KEY}}, {"keys": {"LH_API_KEY": 'has whitespace'}}, {"keys": {"LH_API_KEY": {"secret": KEY}}}, {"unexpected": KEY}):
        response = update(client, body)
        assert response.status_code in {400, 422}
        assert KEY not in response.text
    assert _api_key('lh') == ''


def test_catalog_contains_direct_official_service_key_links(client):
    services = client.get('/api/integrations').json()['services']
    assert len(services) == 6
    assert all(s['key_url'].startswith('https://www.data.go.kr/data/') or s['key_url'] == 'https://aistudio.google.com/apikey' for s in services)


def test_database_error_diagnostics_hide_secret_parameters(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'errors.db'}")
    with engine.connect() as connection:
        with pytest.raises(SQLAlchemyError) as error:
            connection.execute(text('INSERT INTO absent_table(value) VALUES (:key)'), {'key': KEY})
        assert KEY not in str(error.value)
    engine.dispose()


def test_hosted_bootstrap_needs_valid_hash_and_preserves_existing_owner(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'bootstrap.db'}")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        monkeypatch.delenv('INTEGRATIONS_ADMIN_TOKEN_SHA256', raising=False)
        assert not settings.initialize_hosted_admin(session)
        monkeypatch.setenv('INTEGRATIONS_ADMIN_TOKEN_SHA256', 'not-a-hash')
        with pytest.raises(RuntimeError):
            settings.initialize_hosted_admin(session)
        digest = hashlib.sha256(TOKEN.encode()).hexdigest()
        monkeypatch.setenv('INTEGRATIONS_ADMIN_TOKEN_SHA256', digest)
        assert settings.initialize_hosted_admin(session)
        session.commit()
        monkeypatch.setenv('INTEGRATIONS_ADMIN_TOKEN_SHA256', hashlib.sha256(b'replacement').hexdigest())
        assert not settings.initialize_hosted_admin(session)
        assert settings.setting_value(settings.ADMIN_HASH, session) == digest
    engine.dispose()
