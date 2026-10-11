"""Transient responses and partial feeds recover without losing ready rows."""
import asyncio
from datetime import date

import httpx
import pytest

from app.ingest import common, ih, reb
from app.ingest.common import FeedError


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['01', '02', '04', '05'])
async def test_success_http_with_known_transient_result_code_is_retried(code, monkeypatch):
    waits = []
    async def wait(seconds):
        waits.append(seconds)
    monkeypatch.setattr(common.asyncio, 'sleep', wait)
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={'response': {'header': {
                'resultCode': code, 'resultMsg': str(request.url),
            }}})
        return httpx.Response(200, json={'response': {'header': {'resultCode': '00'},
                                                    'body': {'items': []}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        body = await common.get_json(client, 'https://official.example/api', {'serviceKey': 'secret-value'})
    assert body['response']['header']['resultCode'] == '00'
    assert len(calls) == 2 and waits == [0.5]


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code', [(200, '20'), (503, '30'), (403, '01'), (200, '22'), (200, '03')])
async def test_auth_quota_no_data_and_auth_http_failures_do_not_retry(status, code, monkeypatch):
    calls = []
    async def no_wait(seconds):
        raise AssertionError('A nontransient failure cannot retry')
    monkeypatch.setattr(common.asyncio, 'sleep', no_wait)
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={'response': {'header': {
            'resultCode': code, 'resultMsg': str(request.url),
        }}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FeedError) as failure:
            await common.get_json(client, 'https://official.example/api', {'serviceKey': 'private-key'})
    assert len(calls) == 1 and not failure.value.retryable
    assert 'private-key' not in str(failure.value) and 'official.example' not in str(failure.value)


@pytest.mark.asyncio
async def test_transient_retry_remains_bounded_and_does_not_expose_response(monkeypatch):
    waits = []
    async def wait(seconds):
        waits.append(seconds)
    monkeypatch.setattr(common.asyncio, 'sleep', wait)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'response': {'header': {
            'resultCode': '05', 'resultMsg': str(request.url),
        }}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FeedError) as failure:
            await common.get_json(client, 'https://official.example/api', {'serviceKey': 'private-key'})
    assert len(calls) == 3 and waits == [0.5, 1.0]
    assert failure.value.result_code == '05' and failure.value.retryable
    assert 'private-key' not in str(failure.value) and 'official.example' not in str(failure.value)


def reb_detail(number, *, current=False):
    return {'HOUSE_MANAGE_NO': str(number), 'PBLANC_NO': str(number), 'HOUSE_NM': f'공고 {number}',
            'RCRIT_PBLANC_DE': '20261001' if current else '20260501',
            'GNRL_RCEPT_BGNDE': '20261015' if current else '20260515'}


@pytest.mark.asyncio
async def test_reb_streams_bounded_archive_batches_before_later_model_wait():
    batches = []
    current_batches = []
    active = peak = 0
    blocked = asyncio.Event()
    release = asyncio.Event()
    async def handler(request):
        nonlocal active, peak
        operation = request.url.path.rsplit('/', 1)[-1]
        if operation == reb.PAIRS[0].detail:
            details = [reb_detail(1, current=True), *(reb_detail(i) for i in range(2, 15))]
            return httpx.Response(200, json={'data': details, 'totalCount': len(details)})
        if operation in {pair.detail for pair in reb.PAIRS}:
            return httpx.Response(200, json={'data': [], 'totalCount': 0})
        number = request.url.params['cond[HOUSE_MANAGE_NO::EQ]']
        active += 1
        peak = max(active, peak)
        try:
            await asyncio.sleep(0)
            if number == '14':
                blocked.set()
                await release.wait()
            return httpx.Response(200, json={'data': [{'HOUSE_TY': '84A', 'LTTOT_TOP_AMOUNT': '10000'}]})
        finally:
            active -= 1
    async def on_rows(rows):
        batches.append([row['external_id'].rsplit(':', 1)[-1] for row in rows])
        rows[0]['title'] = 'callback-only mutation'
    async def on_current(rows):
        current_batches.append([row['external_id'].rsplit(':', 1)[-1] for row in rows])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        task = asyncio.create_task(reb.collect(client, 'private-key', date(2026, 5, 1), date(2026, 10, 31),
            today=date(2026, 10, 11), on_current_rows=on_current, on_rows=on_rows))
        try:
            await asyncio.wait_for(blocked.wait(), timeout=2)
            assert batches == [['1'], [str(i) for i in range(2, 8)], [str(i) for i in range(8, 14)]]
            assert current_batches == [['1']] and not task.done()
        finally:
            release.set()
        rows = await task
    assert len(rows) == 14 and peak == reb.MODEL_CONCURRENCY == 3
    assert all(row['title'] != 'callback-only mutation' for row in rows)
    assert all(row['prices'][0]['amount_krw'] == 100_000_000 for row in rows)


@pytest.mark.asyncio
async def test_reb_partial_model_failure_delivers_ready_siblings_before_safe_failure(monkeypatch):
    batches = []
    async def get_body(client, url, params, **kwargs):
        if url.endswith(reb.PAIRS[0].detail):
            return {'data': [reb_detail(1), reb_detail(2), reb_detail(3)]}
        if url.rsplit('/', 1)[-1] in {pair.detail for pair in reb.PAIRS}:
            return {'data': []}
        if params['cond[HOUSE_MANAGE_NO::EQ]'] == '2':
            raise FeedError('상위 API 연결 실패: ReadTimeout', retryable=True)
        return {'data': [{'HOUSE_TY': '84A', 'LTTOT_TOP_AMOUNT': '10000'}]}
    monkeypatch.setattr(reb, 'get_json', get_body)
    async def on_rows(rows):
        batches.extend(rows)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail('No live HTTP'))) as client:
        with pytest.raises(FeedError, match='ReadTimeout'):
            await reb.collect(client, 'private-key', date(2026, 5, 1), date(2026, 10, 31),
                today=date(2026, 10, 11), on_rows=on_rows)
    assert [row['external_id'].rsplit(':', 1)[-1] for row in batches] == ['1', '3']
    assert all('private-key' not in str(row) for row in batches)


@pytest.mark.asyncio
async def test_ih_page_is_delivered_before_later_connection_error(monkeypatch):
    calls = []
    batches = []
    async def no_delay(seconds):
        return None
    monkeypatch.setattr(common.asyncio, 'sleep', no_delay)
    def handler(request):
        page = int(request.url.params['pageNo'])
        calls.append(page)
        if page == 2:
            raise httpx.ConnectError(str(request.url), request=request)
        return httpx.Response(200, json={'header': {'resultCode': '200'}, 'body': {
            'totalCount': 31, 'posts': [{'sj': f'분양 {i}', 'link': f'https://official.example/notice/{i}',
                'seNm': '분양', 'crtYmd': '2026-10-01'} for i in range(30)],
        }})
    async def on_rows(rows):
        batches.extend(rows)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FeedError, match='ConnectError') as failure:
            await ih.collect(client, 'private-key', date(2026, 5, 1), date(2026, 10, 31), on_rows=on_rows)
    assert len(batches) == 30 and calls == [1, 2, 2, 2]
    assert 'private-key' not in str(failure.value) and 'official.example' not in str(failure.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('category,label', [
    ('certificate', 'SSLCertVerificationError'), ('dns', 'gaierror'),
    ('refused', 'ConnectionRefusedError'), ('timeout', 'TimeoutError'),
])
async def test_connect_error_reports_only_allowlisted_nested_cause(category, label):
    import socket
    import ssl
    categories = {'certificate': ssl.SSLCertVerificationError, 'dns': socket.gaierror,
                  'refused': ConnectionRefusedError, 'timeout': TimeoutError}
    secret = 'serviceKey=private-secret-value https://official.example/private'
    def handler(request):
        cause = categories[category](secret)
        middle = RuntimeError(secret)
        middle.__context__ = cause
        error = httpx.ConnectError(secret, request=request)
        error.__cause__ = middle
        raise error
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FeedError) as failure:
            await common.get_json(client, 'https://official.example/api', {'serviceKey': 'private-key'}, attempts=1)
    assert str(failure.value) == f'상위 API 연결 실패: ConnectError ({label})'
    assert failure.value.retryable
    assert 'private' not in str(failure.value) and 'official.example' not in str(failure.value)


@pytest.mark.asyncio
async def test_unknown_secret_bearing_cause_and_exception_cycle_are_not_exposed():
    UnrecognizedSecretClass = type('PrivateKeyIsSensitive123', (RuntimeError,), {})
    def handler(request):
        cause = UnrecognizedSecretClass('secret-key in exception args and URL')
        error = httpx.ConnectError('serviceKey=secret-key', request=request)
        cause.__cause__ = error
        error.__context__ = cause
        raise error
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FeedError) as failure:
            await common.get_json(client, 'https://official.example/api', {'serviceKey': 'private-key'}, attempts=1)
    assert str(failure.value) == '상위 API 연결 실패: ConnectError'
    assert 'PrivateKeyIsSensitive123' not in str(failure.value)
    assert 'secret' not in str(failure.value) and 'private' not in str(failure.value)


def test_network_cause_traversal_is_bounded_and_static_for_subclasses():
    cause = TimeoutError('secret-value')
    for _ in range(20):
        wrapper = RuntimeError('private-url')
        wrapper.__cause__ = cause
        cause = wrapper
    assert common._network_failure_cause(cause) is None
    SecretNamedSubclass = type('SecretApiKey123', (ConnectionRefusedError,), {})
    assert common._network_failure_cause(SecretNamedSubclass('private')) == 'ConnectionRefusedError'
