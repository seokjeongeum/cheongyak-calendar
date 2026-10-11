"""CPU timeouts stop the parser and converter, not just their awaiter."""
import asyncio
import io
import json
import os
from pathlib import Path
import sys

from pypdf import PdfWriter
import pytest

from app.extract import pipeline


@pytest.mark.asyncio
async def test_real_local_process_reads_public_pdf_without_thread_executor():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    result = await pipeline._isolated_document_operation('interpret', url='https://www.applyhome.co.kr/current.pdf',
        data=buffer.getvalue(), content_type='application/pdf', payload={}, digest='blank-public-document')
    assert result == {'has_text': False}


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
