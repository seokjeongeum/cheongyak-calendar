"""Shared API/worker credential storage and authenticated settings API."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import SessionLocal, get_session, init_db
from app.models import IntegrationSetting

CATALOG = [
    ("DATA_GO_KR_API_KEY", "공공데이터 공통 키 · 청약홈", "https://www.data.go.kr/data/15098547/openapi.do"),
    ("MYHOME_API_KEY", "마이홈", "https://www.data.go.kr/data/15108420/openapi.do"),
    ("LH_API_KEY", "LH", "https://www.data.go.kr/data/15058530/openapi.do"),
    ("IH_API_KEY", "iH 인천도시공사", "https://www.data.go.kr/data/15149725/openapi.do"),
    ("CHEONGYAK_COMPETITION_API_KEY", "청약 경쟁률", "https://www.data.go.kr/data/15098905/openapi.do"),
    ("GEMINI_API_KEY", "Gemini 문서 추출 · 선택", "https://aistudio.google.com/apikey"),
]
KEY_NAMES = {item[0] for item in CATALOG}
CONFIRMATION = "GEMINI_UNBILLED_PROJECT_CONFIRMED"
ADMIN_HASH = "_admin_token_hash"
router = APIRouter(prefix="/api/integrations", tags=["API 연결 설정"])


def initialize_hosted_admin(session: Session | None = None) -> bool:
    """Bootstrap a fresh hosted database from a hash, preserving existing owners.

    The raw administrator credential stays in the owner's private connection
    link. Neither the image nor Railway variables contain that credential.
    """
    digest = os.getenv("INTEGRATIONS_ADMIN_TOKEN_SHA256", "").strip().lower()
    if not digest:
        return False
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RuntimeError("Invalid hosted administrator hash configuration")
    if session is None:
        with SessionLocal() as selected:
            created = initialize_hosted_admin(selected)
            selected.commit()
            return created
    if session.get(IntegrationSetting, ADMIN_HASH) is not None:
        return False
    insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    result = session.execute(insert(IntegrationSetting).values(name=ADMIN_HASH, value=digest).on_conflict_do_nothing(index_elements=[IntegrationSetting.name]))
    return result.rowcount == 1


def setting_value(name: str, session: Session | None = None) -> str:
    if session is None:
        with SessionLocal() as selected:
            return setting_value(name, selected)
    try:
        row = session.get(IntegrationSetting, name)
    except OperationalError as exc:
        # Standalone legacy SQLite extractors may run before API/worker init.
        # Do not hide connection failures or PostgreSQL migration problems.
        if session.bind is not None and session.bind.dialect.name == "sqlite" and "no such table: integration_settings" in str(exc.orig):
            session.rollback()
            return os.getenv(name, "").strip()
        raise
    # An explicit empty saved value disables an inherited environment key.
    return row.value if row is not None else os.getenv(name, "").strip()


def put_value(session: Session, name: str, value: str) -> None:
    row = session.get(IntegrationSetting, name)
    if row is None:
        session.add(IntegrationSetting(name=name, value=value))
    else:
        row.value = value


def require_admin(request: Request, session: Session = Depends(get_session)) -> None:
    row = session.get(IntegrationSetting, ADMIN_HASH)
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    digest = hashlib.sha256(token.encode()).hexdigest()
    if row is None or not token or not hmac.compare_digest(row.value, digest):
        raise HTTPException(401, "관리자 인증키를 확인하세요.")


def public_settings(session: Session) -> dict:
    return {
        "admin_initialized": session.get(IntegrationSetting, ADMIN_HASH) is not None,
        "services": [
            {"name": name, "label": label, "key_url": url,
             "configured": bool(setting_value(name, session)),
             "storage": "server" if session.get(IntegrationSetting, name) is not None else "environment",
             "uses_shared_key": name not in {"DATA_GO_KR_API_KEY", "GEMINI_API_KEY"} and not setting_value(name, session) and bool(setting_value("DATA_GO_KR_API_KEY", session))}
            for name, label, url in CATALOG
        ],
        "gemini_unbilled_confirmed": setting_value(CONFIRMATION, session).lower() in {"1", "true", "yes"},
    }


@router.get("")
def get_settings(response: Response, session: Session = Depends(get_session)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return public_settings(session)


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: dict[str, SecretStr] = Field(default_factory=dict)
    gemini_unbilled_confirmed: bool | None = None


@router.put("", dependencies=[Depends(require_admin)])
def update_settings(body: SettingsUpdate, response: Response, session: Session = Depends(get_session)) -> dict:
    if set(body.keys) - KEY_NAMES:
        raise HTTPException(400, "지원하지 않는 서비스입니다.")
    for secret in body.keys.values():
        value = secret.get_secret_value().strip()
        if len(value) > 4096 or any(char.isspace() for char in value):
            raise HTTPException(400, "API 키에는 공백을 넣을 수 없습니다.")
    for name, secret in body.keys.items():
        put_value(session, name, secret.get_secret_value().strip())
    if body.gemini_unbilled_confirmed is not None:
        put_value(session, CONFIRMATION, "1" if body.gemini_unbilled_confirmed else "0")
    # Changing the extraction key invalidates the old billing confirmation.
    if "GEMINI_API_KEY" in body.keys and body.gemini_unbilled_confirmed is not True:
        put_value(session, CONFIRMATION, "0")
    session.commit()
    response.headers["Cache-Control"] = "no-store"
    return public_settings(session)


def main() -> None:
    """Generate/rotate a server administrator token; only its hash is stored."""
    init_db()
    token = secrets.token_urlsafe(32)
    with SessionLocal() as session:
        put_value(session, ADMIN_HASH, hashlib.sha256(token.encode()).hexdigest())
        session.commit()
    print(token)


if __name__ == "__main__":
    main()
