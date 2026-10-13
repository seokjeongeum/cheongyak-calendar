"""Current published representations remain readable without a project catalog."""
import copy
import hashlib
import io

import httpx
from pypdf import PdfWriter
import pytest

from app.extract import pipeline
from app.extract.official_rules import PARSER_VERSION

PAGE = "https://apply.lh.or.kr/lhapply/notice.do?panId=2027999888"
PDF = "https://apply.lh.or.kr/lhapply/lhFile.do?fileid=910002"
HWP = "https://apply.lh.or.kr/lhapply/lhFile.do?fileid=910001"


def paired_html():
    return ("<a href=\"javascript:fileDownLoad('910001');\">2027.04.07 정정 입주자모집공고.hwp</a>"
            "<a href=\"javascript:fileDownLoad('910002');\">2027.04.07 정정 입주자모집공고.pdf</a>")


def test_pdf_preference_preserves_correction_and_latest_publication_priority():
    assert pipeline.find_document_links(paired_html(), PAGE) == [PDF, HWP]
    older = paired_html().replace("2027.04.07", "2027.04.06")
    newer = "<a href=\"javascript:fileDownLoad('910003');\">2027.04.08 정정 입주자모집공고.hwp</a>"
    assert pipeline.find_document_links(older + newer, PAGE)[0].endswith("fileid=910003")
    original = "<a href=\"javascript:fileDownLoad('910004');\">입주자모집공고.pdf</a>"
    assert pipeline.find_document_links(original + newer, PAGE)[0].endswith("fileid=910003")


@pytest.mark.asyncio
async def test_current_paired_pdf_retires_old_hwp_failure_without_converter_or_hwp_request(monkeypatch):
    digest = hashlib.sha256(b"current-published-pdf").hexdigest()
    fact = {"kind": "age_min", "value": 19, "effect": "eligibility", "verification": "official",
            "source": "official_document_parser", "parser_version": PARSER_VERSION,
            "document_hash": digest, "evidence_url": PDF}
    coverage = {**fact, "kind": "condition_coverage", "effect": "metadata", "status": "complete", "scopes": []}
    payload = {"official_url": PAGE, "document_hash": digest, "rules_complete": True,
               "rules": [fact, coverage, pipeline._diagnostics_rule([
                    pipeline.document_diagnostic("conversion", "hwp_conversion_failed", HWP)], "unreadable", digest)], "prices": []}
    attempts = []
    async def extract(url, client, *, payload):
        attempts.append(url)
        assert url == PDF
        return {"rules": [copy.deepcopy(fact), copy.deepcopy(coverage)], "status": "complete",
                "document_hash": digest, "document_url": PDF,
                "diagnostics": [pipeline.document_diagnostic("decode", "document_read", PDF, status="ok")]}
    monkeypatch.setattr(pipeline, "extract_local_document", extract)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=paired_html()))) as client:
        result = await pipeline.enrich_notice(payload, client, known_document_hash=digest, allow_gemini=False)
    assert attempts == [PDF] and result["document_hash"] == digest and result["rules_complete"]
    diagnostics = next(rule for rule in result["rules"] if rule["kind"] == "document_diagnostics")
    assert diagnostics["status"] == "complete"
    assert all(entry["code"] != "hwp_conversion_failed" for entry in diagnostics["diagnostics"])


@pytest.mark.asyncio
async def test_failed_current_download_keeps_reviewed_same_hash_coverage_and_true_failure():
    fact = {"kind": "age_min", "value": 19, "effect": "eligibility", "verification": "official",
            "source": "official_document_parser", "parser_version": PARSER_VERSION,
            "document_hash": "reviewed-current-source", "evidence_url": PDF}
    coverage = {**fact, "kind": "condition_coverage", "effect": "metadata", "status": "complete", "scopes": []}
    payload = {"official_url": PAGE, "document_hash": fact["document_hash"], "rules_complete": True,
               "rules": [fact, coverage], "prices": [{"unit_type": "future-A", "amount_krw": 300000000}]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403))) as client:
        result = await pipeline.enrich_notice(copy.deepcopy(payload), client, known_document_hash=fact["document_hash"], allow_gemini=False)
    assert result["document_hash"] == payload["document_hash"] and result["rules_complete"]
    assert all(rule in result["rules"] for rule in payload["rules"])
    assert result["prices"] == payload["prices"]
    diagnostics = next(rule for rule in result["rules"] if rule["kind"] == "document_diagnostics")
    assert diagnostics["status"] == "unreadable"
    assert any(entry["stage"] == "download" and entry["status"] == "error" for entry in diagnostics["diagnostics"])


@pytest.mark.parametrize("extension", ["hwp", "hwpx"])
def test_pdf_signature_remains_authoritative_when_official_filename_uses_hwp_extension(monkeypatch, extension):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    stream = io.BytesIO()
    writer.write(stream)
    data = stream.getvalue()
    monkeypatch.setattr(pipeline, "_hwp_as_pdf", lambda *args: (_ for _ in ()).throw(AssertionError("PDF needs no conversion")))
    assert len(pipeline.document_pages(f"https://apply.lh.or.kr/current.{extension}", data, "application/octet-stream")) == 1
    assert pipeline._document_part(f"https://apply.lh.or.kr/current.{extension}", data, "application/octet-stream")["inlineData"]["mimeType"] == "application/pdf"
