"""Local document CPU work in a disposable, memory-bounded process.

The parent terminates this process group on timeout/cancellation. It receives
only public notice bytes and facts; this module performs no network or DB work.
"""
from __future__ import annotations

import base64
import json
import re
import sys

from .pipeline import document_exception_type


def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)
    except (ImportError, OSError, ValueError):
        pass
    from .pipeline import MAX_DOCUMENT_BYTES, _document_part, document_pages
    from .official_rules import parse_official_rules

    request = json.loads(sys.stdin.buffer.read(24 * 1024 * 1024 + 1))
    data = base64.b64decode(request['data'], validate=True)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError('Document exceeds input limit')
    if request['operation'] == 'model_part':
        return {'part': _document_part(request['url'], data, request['content_type'])}
    if request['operation'] != 'interpret':
        raise ValueError('Unknown local operation')
    try:
        pages = document_pages(request['url'], data, request['content_type'])
    except Exception as exc:
        return {'has_text': False, 'error_stage': 'decode', 'exception_type': document_exception_type(exc)}
    has_text = any(page['text'].strip() for page in pages)
    if not has_text:
        return {'has_text': False}
    try:
        payload = {**(request.get('payload') or {}), 'document_page_count': len(pages)}
        result = parse_official_rules(pages, url=request['url'], digest=request['digest'], payload=payload)
    except Exception as exc:
        return {'has_text': True, 'error_stage': 'interpretation', 'exception_type': document_exception_type(exc)}
    if result.get('identity_status') != 'mismatch':
        rules = result.get('rules', [])
        national_rank = any(rule.get('kind') == 'application_method' and rule.get('value') == 'apt_ranked'
                            and rule.get('housing_kind') == 'national' for rule in rules)
        if national_rank and not any(rule.get('kind') == 'rank_requirements' and rule.get('complete') for rule in rules):
            from pdfminer.pdfexceptions import PDFException
            from .rank_tables import rank_pdf_pages
            try:
                rank_pages = rank_pdf_pages(data, pages)
                if rank_pages != pages:
                    result = parse_official_rules(pages, url=request['url'], digest=request['digest'], payload=payload,
                                                  rank_pages=rank_pages)
            except (PDFException, ValueError, TypeError, MemoryError):
                # Coordinate recovery is supplementary to readable source facts.
                pass
        from .price_tables import parse_price_tables
        prices = parse_price_tables(pages, url=request['url'], digest=request['digest'],
                                    payload={**payload, 'rules': [*payload.get('rules', []), *result.get('rules', [])]})
        if prices['price_identity_confirmed']:
            result['prices'] = [*result.get('prices', []), *prices['prices']]
            result['rules'] = [*result.get('rules', []), *prices['rules']]
            result['price_identity_confirmed'] = True
        for page in pages:
            flat = " ".join(page["text"].split())
            reference = re.search(r"[^■]{0,210}(?:최초|기존|당초)\s*(?:입주자\s*)?모집공고문?(?:을|를)\s*준용[^■.]{0,65}", flat)
            if reference:
                result["original_notice_reference"] = {"evidence_page": page["page"], "evidence_text": reference[0].strip()}
                break
    return {'has_text': True, 'result': result}


if __name__ == '__main__':
    try:
        result = main()
        sys.stdout.write(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        sys.stdout.write(json.dumps({'has_text': False, 'error_stage': 'process',
                                    'exception_type': document_exception_type(exc)}))
