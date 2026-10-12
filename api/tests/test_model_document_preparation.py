"""Failed HWP/HWPX model preparation retains local facts and a safe cause."""

import json

import httpx
import pytest

from app import integration_settings
from app.extract import pipeline


@pytest.mark.asyncio
@pytest.mark.parametrize("data,source_format", [
    (b"PK\x03\x04public-hwpx", "hwpx"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1public-hwp", "hwp"),
])
@pytest.mark.parametrize("result", [
    {"has_text": False, "error_stage": "process", "exception_type": "MemoryError"},
    {"part": {}},
])
async def test_missing_or_invalid_model_part_is_a_typed_safe_processing_failure(monkeypatch, data, source_format, result):
    monkeypatch.setattr(pipeline, "extraction_configured", lambda: True)
    monkeypatch.setattr(integration_settings, "setting_value", lambda _: "fictional-test-key")

    async def process(*args, **kwargs):
        return result

    def handler(request):
        assert request.url.host == "www.myhome.go.kr"  # No model API call after failed conversion.
        return httpx.Response(200, content=data)

    monkeypatch.setattr(pipeline, "_isolated_document_operation", process)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(pipeline.ModelDocumentPreparationFailed) as error:
            await pipeline.extract_document("https://www.myhome.go.kr/notice.hwp", client)
    entry = error.value.diagnostics[0]
    assert entry["code"] == "model_document_preparation_failed"
    assert entry["source_format"] == source_format
    assert entry["exception_type"] == result.get("exception_type", "ValueError")
    assert entry["error_stage"] == "process"
    assert "fictional-test-key" not in json.dumps(entry)


@pytest.mark.asyncio
async def test_model_conversion_failure_does_not_discard_successful_local_review(monkeypatch):
    url = "https://www.myhome.go.kr/notice.hwpx"
    digest = "current-public-document"
    rule = {"kind": "age_min", "effect": "admission", "verification": "official",
        "source": "official_document_parser", "value": 19, "supply_type": "general",
        "document_hash": digest, "evidence_url": url}

    async def local(*args, **kwargs):
        return {"document_hash": digest, "document_url": url, "status": "partial",
            "rules": [rule], "diagnostics": [pipeline.document_diagnostic(
                "decode", "document_read", url, status="ok") ]}

    async def process(*args, **kwargs):
        return {"has_text": False, "error_stage": "process", "exception_type": "ValueError",
            "ignored_private_message": "private-converter-path"}

    def handler(request):
        assert request.url.host == "www.myhome.go.kr"
        return httpx.Response(200, content=b"PK\x03\x04public-hwpx")

    monkeypatch.setattr(pipeline, "extraction_configured", lambda: True)
    monkeypatch.setattr(integration_settings, "setting_value", lambda _: "fictional-test-key")
    monkeypatch.setattr(pipeline, "extract_local_document", local)
    monkeypatch.setattr(pipeline, "_isolated_document_operation", process)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await pipeline.enrich_notice({"official_url": url}, client)
    assert result["document_hash"] == digest and rule in result["rules"]
    assert result["local_extraction_status"] == "partial"
    diagnostic = next(r for r in result["rules"] if r["kind"] == "document_diagnostics")
    entry = next(d for d in diagnostic["diagnostics"] if d["code"] == "model_document_preparation_failed")
    assert entry["exception_type"] == "ValueError" and entry["error_stage"] == "process"
    assert any(d["code"] == "document_read" for d in diagnostic["diagnostics"])
    assert "private-converter-path" not in json.dumps(result)
