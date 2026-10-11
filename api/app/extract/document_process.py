"""Local document CPU work in a disposable, memory-bounded process.

The parent terminates this process group on timeout/cancellation. It receives
only public notice bytes and facts; this module performs no network or DB work.
"""
from __future__ import annotations

import base64
import json
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
    return {'has_text': True, 'result': result}


if __name__ == '__main__':
    try:
        result = main()
        sys.stdout.write(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        sys.stdout.write(json.dumps({'has_text': False, 'error_stage': 'process',
                                    'exception_type': document_exception_type(exc)}))
