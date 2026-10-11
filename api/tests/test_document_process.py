"""CPU timeouts stop the parser and converter, not just their awaiter."""
import asyncio
from datetime import date, datetime, timezone
import io
import json
import os
from pathlib import Path
import sys

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest

from app.extract import pipeline


def text_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
        DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    content = DecodedStreamObject()
    content.set_data(b'BT /F1 12 Tf 30 700 Td (Public housing recruitment 2026.09.30) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(content)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_real_local_process_reads_public_pdf_without_thread_executor():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    result = await pipeline._isolated_document_operation('interpret', url='https://www.applyhome.co.kr/current.pdf',
        data=buffer.getvalue(), content_type='application/pdf', payload={}, digest='blank-public-document')
    assert result == {'has_text': False}


@pytest.mark.asyncio
async def test_real_child_reads_nonblank_pdf_with_retained_notice_and_event_dates():
    from app.models import Notice, NoticeEvent
    from app.repository import _existing_payload

    notice = Notice(source='lh', external_id='new-public-notice', category='public_sale',
        title='New public housing recruitment', announcement_date=date(2026, 9, 30),
        official_url='https://apply.lh.or.kr/current.pdf', rules=[], rules_complete=False,
        events=[NoticeEvent(kind='application', label='Application',
            start_date=date(2026, 10, 27), end_date=date(2027, 8, 31))])
    payload = _existing_payload(notice)
    assert isinstance(payload['announcement_date'], date)
    assert isinstance(payload['events'][0]['start_date'], date)
    payload['rules'].append({'kind': 'public_record', 'recorded_at': datetime(2026, 10, 1, tzinfo=timezone.utc)})
    result = await pipeline._isolated_document_operation('interpret', url=notice.official_url,
        data=text_pdf(), content_type='application/pdf', payload=payload, digest='new-public-document')
    assert result['has_text'] is True and 'result' in result and 'error_stage' not in result
    # Sending to the child must not rewrite the retained source snapshot.
    assert payload['events'][0]['end_date'] == date(2027, 8, 31)
    assert isinstance(payload['rules'][0]['recorded_at'], datetime)


@pytest.mark.asyncio
async def test_child_protocol_rejects_unknown_objects_without_stringifying_them():
    class Unsupported:
        def __str__(self):
            raise AssertionError('Arbitrary object values must not be serialized')
    with pytest.raises(TypeError, match='Unsupported local document input type'):
        await pipeline._isolated_document_operation('interpret', url='https://apply.lh.or.kr/current.pdf',
            data=text_pdf(), content_type='application/pdf', payload={'unexpected': Unsupported()}, digest='new-document')


@pytest.mark.parametrize('stage,error', [('decode', MemoryError('private-value')),
                                      ('interpretation', ValueError('private-value'))])
def test_child_failure_reports_only_allowed_exception_name(monkeypatch, stage, error):
    import base64
    import resource
    from types import SimpleNamespace
    from app.extract import document_process
    monkeypatch.setattr(resource, 'setrlimit', lambda *args: None)
    request = {'operation': 'interpret', 'url': 'https://apply.lh.or.kr/current.pdf',
        'data': base64.b64encode(text_pdf()).decode(), 'content_type': 'application/pdf',
        'payload': {}, 'digest': 'new-document'}
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode())))
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(pipeline, 'document_pages', fail if stage == 'decode' else lambda *args: [{'page': 1, 'text': 'Public text'}])
    if stage == 'interpretation':
        monkeypatch.setattr('app.extract.official_rules.parse_official_rules', fail)
    result = document_process.main()
    assert result == {'has_text': stage == 'interpretation', 'error_stage': stage,
                      'exception_type': type(error).__name__}
    assert 'private-value' not in json.dumps(result)


def running(pid):
    path = Path(f'/proc/{pid}/stat')
    if not path.exists():
        return False
    return path.read_text().rsplit(')', 1)[1].split()[0] != 'Z'


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != 'posix', reason='Process groups require POSIX')
@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
async def test_interrupted_parse_stops_its_converter_descendant_and_keeps_loop_responsive(tmp_path, monkeypatch, stop):
    script = tmp_path / 'blocked_converter.py'
    pids = tmp_path / 'pids.json'
    script.write_text('''import json, os, pathlib, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(180)'])
pathlib.Path(sys.argv[1]).write_text(json.dumps([os.getpid(), child.pid]))
time.sleep(180)
''')
    real_spawn = asyncio.create_subprocess_exec
    async def spawn(*args, **kwargs):
        return await real_spawn(sys.executable, str(script), str(pids), **kwargs)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(pipeline, 'LOCAL_PROCESS_TIMEOUT_SECONDS', 0.6 if stop == 'timeout' else 120)
    task = asyncio.create_task(pipeline._isolated_document_operation('interpret', url='https://www.applyhome.co.kr/current.pdf',
        data=b'%PDF-public', content_type='application/pdf', payload={}, digest='blocked-document'))
    ticks = 0
    while not pids.exists() and not task.done() and ticks < 100:
        await asyncio.sleep(0.01)
        ticks += 1
    assert pids.exists() and ticks > 0
    parent, child = json.loads(pids.read_text())
    assert running(parent) and running(child)
    if stop == 'cancel':
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(TimeoutError):
            await task
    for _ in range(50):
        if not running(parent) and not running(child):
            break
        await asyncio.sleep(0.01)
    assert not running(parent) and not running(child)


@pytest.mark.asyncio
async def test_process_output_is_bounded(tmp_path, monkeypatch):
    script = tmp_path / 'oversized_result.py'
    script.write_text('import sys; sys.stdin.buffer.read(); sys.stdout.write("x" * 2048)')
    real_spawn = asyncio.create_subprocess_exec
    async def spawn(*args, **kwargs):
        return await real_spawn(sys.executable, str(script), **kwargs)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(pipeline, 'MAX_PROCESS_OUTPUT_BYTES', 1024)
    with pytest.raises(ValueError, match='output limit'):
        await pipeline._isolated_document_operation('interpret', url='https://www.applyhome.co.kr/current.pdf',
            data=b'%PDF-public', content_type='application/pdf', payload={}, digest='bounded-document')
