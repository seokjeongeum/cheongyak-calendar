"""Shared parsing and HTTP helpers for official notice feeds."""

from __future__ import annotations

import asyncio
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx


class FeedError(RuntimeError):
    """A safe, typed upstream failure suitable for public coverage status."""

    def __init__(
        self, message: str, *, status_code: int | None = None,
        result_code: str | None = None, retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.result_code = result_code
        self.retryable = retryable


def value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        item = row.get(key)
        if item is not None and str(item).strip() not in ("", "null", "None", "-"):
            return item
    return None


def date_iso(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().split("T", 1)[0].split(" ", 1)[0]
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    else:
        text = text.replace(".", "-").replace("/", "-").rstrip("-")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def decimal_number(raw: Any) -> Decimal | None:
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip().replace(",", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return None
    try:
        result = Decimal(text)
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def integer(raw: Any) -> int | None:
    number = decimal_number(raw)
    return int(number) if number is not None and number == number.to_integral_value() else None


def manwon_to_krw(raw: Any) -> int | None:
    """REB housing-type amount fields are explicitly documented in 만원."""
    number = decimal_number(raw)
    if number is None:
        return None
    krw = number * 10_000
    return int(krw) if krw == krw.to_integral_value() else None


def public_url(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    return url if urlparse(url).scheme in ("http", "https") and urlparse(url).netloc else None


def add_event(events: list[dict[str, Any]], kind: str, label: str, start: Any, end: Any = None, audience: str | None = None) -> None:
    start_date = date_iso(start)
    end_date = date_iso(end)
    if start_date is None:
        return
    if end_date is not None and end_date < start_date:
        end_date = None
    event = {"kind": kind, "label": label, "start_date": start_date, "end_date": end_date, "audience": audience}
    if event not in events:
        events.append(event)


_RESULT_CAUSES = {
    "01": "상위 API 처리 오류가 발생했습니다. 기관 서비스 상태를 확인하세요.",
    "02": "상위 API 데이터베이스 오류가 발생했습니다. 잠시 후 다시 확인하세요.",
    "03": "상위 API가 해당 조건의 데이터를 제공하지 않았습니다. 조회 조건을 확인하세요.",
    "04": "상위 API 통신 오류가 발생했습니다. 기관 서비스 상태를 확인하세요.",
    "05": "상위 API 응답 시간이 초과되었습니다. 잠시 후 다시 확인하세요.",
    "10": "상위 API 요청 값이 유효하지 않습니다. API 연동 설정을 확인하세요.",
    "11": "상위 API 필수 요청 값이 없습니다. API 연동 설정을 확인하세요.",
    "12": "신청한 API 서비스를 찾지 못했습니다. 서비스 활용신청을 확인하세요.",
    "20": "API 접근 권한이 없습니다. 해당 서비스 활용신청과 키 권한을 확인하세요.",
    "21": "API 키가 일시 중지되었습니다. 공공데이터포털에서 키 상태를 확인하세요.",
    "22": "API 호출 한도를 초과했습니다. 사용량과 일일 한도를 확인하세요.",
    "30": "등록되지 않은 API 키입니다. 발급 키와 서비스 활용신청을 확인하세요.",
    "31": "API 키 유효기간이 지났습니다. 키를 재발급하세요.",
    "32": "등록되지 않은 접속 IP입니다. API 키의 IP 제한을 확인하세요.",
}
_RESULT_ALIASES = {
    "SERVICE_KEY_IS_NOT_REGISTERED_ERROR": "30",
    "SERVICE_ACCESS_DENIED_ERROR": "20",
    "DEADLINE_HAS_EXPIRED_ERROR": "31",
    "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR": "22",
    "UNREGISTERED_IP_ERROR": "32",
}
_SUCCESS_CODES = {"0", "00", "000", "200", "Y", "SUCCESS"}


def _result_code(raw: Any) -> str | None:
    if raw is None:
        return None
    code = str(raw).strip().upper()
    if code in _RESULT_ALIASES:
        return _RESULT_ALIASES[code]
    if re.fullmatch(r"\d{1,3}", code):
        return code.zfill(2)
    if code in _SUCCESS_CODES:
        return code
    return None


def _coded_error(raw: Any, status_code: int | None) -> FeedError | None:
    if raw is None:
        return None
    code = _result_code(raw)
    if code in _SUCCESS_CODES:
        return None
    if code is None:
        return FeedError("상위 API 오류 응답. 기관 API 상태를 확인하세요.", status_code=status_code,
                         retryable=status_code in {429, 500, 502, 503, 504})
    cause = _RESULT_CAUSES.get(code, "상위 API에서 오류를 반환했습니다. 기관 API 상태를 확인하세요.")
    prefix = f"상위 API 오류 코드 {code}"
    if status_code is not None:
        prefix = f"상위 API HTTP {status_code}, 오류 코드 {code}"
    return FeedError(f"{prefix}: {cause}", status_code=status_code, result_code=code,
                     retryable=status_code in {429, 500, 502, 503, 504})


def _http_error(status_code: int) -> FeedError:
    if status_code in {401, 403}:
        cause = "API 인증 또는 접근 권한을 확인하세요."
    elif status_code == 429:
        cause = "API 호출 한도를 초과했습니다. 사용량과 일일 한도를 확인하세요."
    elif status_code == 404:
        cause = "API 주소 또는 서비스 활용신청 상태를 확인하세요."
    elif status_code >= 500:
        cause = "상위 기관 서버 상태를 확인하세요."
    else:
        cause = "API 요청 값과 서비스 상태를 확인하세요."
    return FeedError(f"상위 API HTTP {status_code}: {cause}", status_code=status_code,
                     retryable=status_code in {429, 500, 502, 503, 504})


def gateway_error(body: Any, *, status_code: int | None = None) -> FeedError | None:
    """Read known error codes, never echoing upstream text or request details."""
    if isinstance(body, list):
        for item in body:
            if isinstance(item, dict) and isinstance(item.get("CMN"), dict):
                common = item["CMN"]
                code = value(common, "CODE", "SS_CODE")
                if code is not None:
                    return _coded_error(code, status_code)
                return None
        return None
    if not isinstance(body, dict):
        return FeedError("상위 API 응답 형식 오류", status_code=status_code)
    service_response = body.get("OpenAPI_ServiceResponse")
    if isinstance(service_response, dict):
        common_header = service_response.get("cmmMsgHeader")
        if isinstance(common_header, dict):
            code = value(common_header, "returnReasonCode", "returnAuthMsg")
            if code is not None:
                return _coded_error(code, status_code) or FeedError(
                    "상위 API 인증 오류 응답. 서비스 활용신청과 키 권한을 확인하세요.", status_code=status_code,
                )
            return FeedError("상위 API 인증 오류 응답. 서비스 활용신청과 키 권한을 확인하세요.",
                             status_code=status_code)
    response = body.get("response")
    header = body.get("header") or (response.get("header") if isinstance(response, dict) else None)
    if isinstance(header, dict):
        code = value(header, "resultCode", "result_code")
        if code is not None:
            return _coded_error(code, status_code)
    error = body.get("error")
    if error:
        code = value(error, "code", "resultCode") if isinstance(error, dict) else None
        return _coded_error(code, status_code) or FeedError(
            "상위 API 오류 응답. 기관 API 상태를 확인하세요.", status_code=status_code,
        )
    return None


async def get_json(client: httpx.AsyncClient, url: str, params: dict[str, Any], *, attempts: int = 3) -> dict[str, Any] | list[Any]:
    """GET with bounded retries for transient errors and no secret-bearing logs."""
    last: FeedError | None = None
    for attempt in range(attempts):
        try:
            response = await client.get(url, params=params, timeout=25)
            try:
                body = response.json()
            except ValueError:
                if response.status_code >= 400:
                    raise _http_error(response.status_code) from None
                raise FeedError("상위 API 응답 JSON 형식 오류") from None
            error = gateway_error(body, status_code=response.status_code if response.status_code >= 400 else None)
            if error:
                raise error
            if response.status_code >= 400:
                raise _http_error(response.status_code)
            return body
        except httpx.RequestError as exc:
            last = FeedError(f"상위 API 연결 실패: {type(exc).__name__}", retryable=True)
        except FeedError as exc:
            last = exc
        if last is not None:
            if not last.retryable or attempt == attempts - 1:
                break
            await asyncio.sleep(0.5 * (2 ** attempt))
    raise last or FeedError("상위 API 호출 실패")


def body_rows(body: dict[str, Any] | list[Any], *keys: str) -> tuple[list[dict[str, Any]], int | None]:
    """Accept common data.go.kr JSON envelopes without guessing field values."""
    if isinstance(body, list):
        total = None
        for item in body:
            if isinstance(item, dict) and isinstance(item.get("CMN"), dict):
                total = integer(value(item["CMN"], "TOTAL_CNT", "ALL_CNT"))
            if isinstance(item, dict):
                for key in keys or ("dsList", "data", "items"):
                    if isinstance(item.get(key), list):
                        return [row for row in item[key] if isinstance(row, dict)], total
        return [], total
    node = body.get("response", body)
    if isinstance(node, dict):
        node = node.get("body", node)
    if not isinstance(node, dict):
        return [], None
    total = integer(value(node, "totalCount", "ALL_CNT", "total_count"))
    for key in keys or ("data", "item", "items", "posts", "dsList"):
        rows = node.get(key)
        if isinstance(rows, dict):
            rows = rows.get("item", rows.get("items", rows))
        if isinstance(rows, dict):
            rows = [rows]
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)], total
    return [], total


def omit_empty_enrichment(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep previously extracted document fields when an API lacks those fields."""
    for key in ("prices", "rules"):
        if not payload.get(key):
            payload.pop(key, None)
    return payload
