import json
import os
import sys
import tempfile
from pathlib import Path

os.environ['TRANSCRIPT_TEST'] = '1'
os.environ['TRANSCRIPT_DATA'] = tempfile.mkdtemp(prefix='transcript-tests-')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
import app
import store
from engine import caption_segments, srt, validate_url

def test_thread_configuration(monkeypatch):
    import engine
    monkeypatch.setattr(engine.os, 'cpu_count', lambda: 8)
    monkeypatch.delenv('TRANSCRIPT_CPU_THREADS', raising=False)
    assert engine.configured_cpu_threads() == 4
    monkeypatch.setenv('TRANSCRIPT_CPU_THREADS', '2')
    assert engine.configured_cpu_threads() == 2
    monkeypatch.setenv('TRANSCRIPT_CPU_THREADS', '32')
    assert engine.configured_cpu_threads() == 8
    for invalid in ('0', '-1', 'four'):
        monkeypatch.setenv('TRANSCRIPT_CPU_THREADS', invalid)
        with pytest.raises(ValueError):
            engine.configured_cpu_threads()

def test_transcription_uses_selected_model_and_configured_threads(monkeypatch):
    import engine
    import av
    import faster_whisper
    from types import SimpleNamespace
    calls = []
    class AudioContainer:
        duration = av.time_base
        streams = SimpleNamespace(audio=[True])
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class FakeModel:
        def __init__(self, model, **options):
            calls.append((model, options))
        def transcribe(self, *args, **kwargs):
            segment = SimpleNamespace(start=0, end=1, text=' Test speech. ')
            return iter([segment]), SimpleNamespace(duration=1, language='en')
    monkeypatch.setattr(av, 'open', lambda *a: AudioContainer())
    monkeypatch.setattr(faster_whisper, 'WhisperModel', FakeModel)
    monkeypatch.setattr(engine, 'CPU_THREADS', 4)
    monkeypatch.setattr(engine.store, 'update', lambda *a, **kw: None)
    result = engine.transcribe({'id': 'test', 'model': 'base', 'language': 'auto'}, 'test.wav')
    assert len(calls) == 1
    assert calls[0][0] == 'base'
    assert calls[0][1]['cpu_threads'] == 4
    assert calls[0][1]['num_workers'] == 1
    assert result['cpu_threads'] == 4
    assert result['model_load_seconds'] >= 0
    assert result['transcribe_seconds'] >= 0
    assert result['segments'][0]['text'] == 'Test speech.'

@pytest.fixture(scope='module')
def client():
    with TestClient(app.app) as client:
        yield client

def test_fast_base_reuses_resident_model_and_fast_decoding(monkeypatch):
    import engine
    import av
    from types import SimpleNamespace
    class AudioContainer:
        duration = av.time_base
        streams = SimpleNamespace(audio=[True])
        def __enter__(self): return self
        def __exit__(self, *args): pass
    calls=[]
    class Resident:
        def transcribe(self, *args, **kwargs):
            calls.append(kwargs)
            return iter([SimpleNamespace(start=0,end=1,text='Hello.')]), SimpleNamespace(duration=1,language='en')
    monkeypatch.setattr(av, 'open', lambda *args: AudioContainer())
    monkeypatch.setattr(engine.store, 'update', lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, 'load_whisper_model', lambda *args: pytest.fail('Resident Base must be reused'))
    resident=Resident()
    for language in ('auto','en'):
        result=engine.transcribe({'id':'test','model':'base-fast','language':language},'test.wav',resident)
        assert result['model_resident'] and result['model_load_seconds']==0
        assert result['source']=='Local Whisper Base fast'
    assert all(c['beam_size']==1 and c['best_of']==1 for c in calls)
    assert [c['language'] for c in calls]==[None,'en']

def token():
    return (store.DATA / 'ACCESS.txt').read_text().split('Agent API token: ')[1].splitlines()[0]

def auth():
    return {'Authorization': 'Bearer ' + token()}

def test_private_routes_require_auth(client):
    assert client.get('/api/jobs').status_code == 401
    assert client.post('/mcp/', json={'jsonrpc':'2.0','method':'initialize','id':1}).status_code == 401
    assert client.get('/data/ACCESS.txt').status_code == 404
    assert client.get('/static/../data/ACCESS.txt').status_code == 404

def test_login_logout_csrf_and_host(client):
    password = (store.DATA / 'ACCESS.txt').read_text().split('Website password: ')[1].splitlines()[0]
    assert client.post('/api/login',json={'password':password}).status_code == 403
    assert client.post('/api/login',json={'password':password},headers={'x-transcript-request':'1','Origin':'https://evil.example'}).status_code == 403
    response = client.post('/api/login',json={'password':password},headers={'x-transcript-request':'1'})
    assert response.status_code == 200
    assert 'HttpOnly' in response.headers['set-cookie']
    assert client.get('/api/jobs').status_code == 200
    assert client.post('/api/logout').status_code == 403
    assert client.post('/api/logout',headers={'x-transcript-request':'1'}).status_code == 200
    assert client.get('/api/jobs').status_code == 401
    assert client.get('/',headers={'host':'evil.example'}).status_code == 400

def test_url_validation_and_cache(client):
    for bad in ['http://youtube.com/watch?v=9LkxI2H3gI0','https://127.0.0.1/','https://youtube.com.evil.com/watch?v=9LkxI2H3gI0','https://youtube.com@127.0.0.1/','https://youtube.com:443/watch?v=9LkxI2H3gI0','https://youtube.com/playlist?list=x']:
        with pytest.raises(ValueError): validate_url(bad)
    first = client.post('/api/jobs',headers=auth(),json={'url':'https://youtu.be/9LkxI2H3gI0?si=tracking'}).json()
    second = client.post('/api/jobs',headers=auth(),json={'url':'https://www.youtube.com/watch?v=9LkxI2H3gI0'}).json()
    assert first['id'] == second['id']
    assert 'input_path' not in first
    assert client.post('/api/jobs',headers=auth(),json={'url':'https://www.youtube.com/watch?v=9LkxI2H3gI0','language':'invalid'}).status_code == 400

def test_full_text_chunks_and_exports(client):
    job = store.create_job(title='Chunk test')
    text = 'word ' * 15000
    result = {'text':text,'segments':[{'start':1.25,'end':2.5,'text':'A & B'}],'source':'test','language':'en'}
    store.update(job['id'],status='done',result=json.dumps(result))
    parts, offset = [], 0
    while True:
        part = app.get_transcript(job['id'],offset,10000)
        parts.append(part['text'])
        if part['next_offset'] is None: break
        offset = part['next_offset']
    assert ''.join(parts) == text
    assert client.get(f"/api/jobs/{job['id']}/download",headers=auth()).text == store.format_output(result)
    assert '00:00:01,250 --> 00:00:02,500' in client.get(f"/api/jobs/{job['id']}/download?format=srt",headers=auth()).text

def test_caption_overlap_preserves_nonoverlap():
    events = {'events':[{'tStartMs':0,'dDurationMs':2000,'segs':[{'utf8':'hello world'}]},{'tStartMs':1000,'dDurationMs':2000,'segs':[{'utf8':'world again'}]},{'tStartMs':5000,'dDurationMs':1000,'segs':[{'utf8':'again'}]}]}
    segments = caption_segments(json.dumps(events),'json3')
    assert [s['text'] for s in segments] == ['hello world','again','again']
    assert caption_segments('WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<b>A &amp; B</b>\n','vtt')[0]['text'] == 'A & B'

def test_invalid_upload(client):
    assert client.post('/api/upload',headers=auth(),files={'file':('bad.exe',b'bad')}).status_code == 400
    assert client.post('/api/upload',headers=auth(),files={'file':('empty.wav',b'')}).status_code == 400

def test_mcp_initialize_and_tools(client):
    headers={**auth(),'Accept':'application/json, text/event-stream'}
    response=client.post('/mcp/',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'test','version':'1'}}})
    assert response.status_code == 200, response.text
    result=client.post('/mcp/',headers=headers,json={'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
    names={t['name'] for t in result.json()['result']['tools']}
    assert names == {'transcribe_url','get_transcription_status','get_transcript'}

def test_mcp_job_lifecycle_and_complete_chunks(client):
    headers = {**auth(), 'Accept': 'application/json, text/event-stream'}
    def call(name, arguments):
        response = client.post('/mcp/', headers=headers, json={
            'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call',
            'params': {'name': name, 'arguments': arguments}})
        assert response.status_code == 200, response.text
        result = response.json()['result']
        assert not result.get('isError'), result
        return result.get('structuredContent') or json.loads(result['content'][0]['text'])
    queued = call('transcribe_url', {'url': 'https://www.instagram.com/p/TestClip123/'})
    assert queued['status'] == 'queued'
    assert (queued['model'], queued['language'], queued['captions']) == ('base-fast', 'auto', 1)
    assert call('get_transcription_status', {'job_id': queued['id']})['status'] == 'queued'
    text = 'Full raw transcript. ' * 2000
    store.update(queued['id'], status='done', result=json.dumps({
        'text': text, 'source': 'test', 'language': 'en', 'segments': []}))
    chunks, offset = [], 0
    while True:
        part = call('get_transcript', {'job_id': queued['id'], 'offset': offset})
        chunks.append(part['text'])
        if part['next_offset'] is None:
            break
        offset = part['next_offset']
    assert ''.join(chunks) == text
    cached = call('transcribe_url', {'url': 'https://www.instagram.com/p/TestClip123/'})
    assert cached['id'] == queued['id']
    assert cached['transcript']['next_offset'] is not None

def test_model_control_and_language_validation(client):
    assert client.get('/api/model').status_code == 401
    assert client.post('/api/model', json={'enabled': False}).status_code == 401
    paused = client.post('/api/model', headers=auth(), json={'enabled': False}).json()
    assert paused['state'] == 'unloaded' and not paused['enabled']
    assert not store.model_enabled()
    from model_runtime import ModelRuntime
    assert not ModelRuntime().enabled  # The preference survives a fresh runtime.
    job = client.post('/api/jobs', headers=auth(), json={'url': 'https://www.instagram.com/p/PausedTest123/'}).json()
    assert job['status'] == 'queued' and job['model'] == 'base-fast'
    assert not app.get_transcription_status(job['id'])['processing_enabled']
    assert client.post('/api/jobs', headers=auth(), json={'url': 'https://www.instagram.com/p/SpanishTest123/', 'language': 'es', 'model': 'sensevoice'}).status_code == 400
    assert client.post('/api/jobs', headers=auth(), json={'url': 'https://www.instagram.com/p/SpanishTest123/', 'language': 'es', 'model': 'base'}).status_code == 202
    client.post('/api/model', headers=auth(), json={'enabled': True})
    assert store.model_enabled()

def test_unload_waits_for_active_job(monkeypatch):
    import asyncio
    from model_runtime import ModelRuntime
    from types import SimpleNamespace
    async def check():
        runtime = ModelRuntime()
        finished, entered = asyncio.Event(), asyncio.Event()
        class Process:
            pid = 99999999
            returncode = None
            stdin = None
            def kill(self): self.returncode = -1
            async def wait(self): return self.returncode
        process = Process()
        async def drain(): pass
        process.stdin = SimpleNamespace(write=lambda data: None, drain=drain)
        runtime.process = process
        async def read(timeout):
            entered.set()
            await finished.wait()
            return {'finished': True}
        runtime._read = read
        task = asyncio.create_task(runtime.run_job('test'))
        await entered.wait()
        status = await runtime.set_enabled(False)
        assert status['state'] == 'unloading' and status['busy']
        assert process.returncode is None
        finished.set()
        assert await task
        assert process.returncode == -1 and runtime.process is None
        assert runtime.state == 'unloaded'
        assert not await runtime.run_job('next')
        await runtime.set_enabled(True)
    asyncio.run(check())

def test_delete_transcript_access_cache_and_active_job_protection(client):
    url = 'https://www.instagram.com/p/DeleteTest123/'
    job = store.create_job(url=url)
    path = '/api/jobs/' + job['id']
    assert client.delete(path).status_code == 401
    assert client.delete(path, headers=auth()).status_code == 409
    assert store.get_job(job['id'])['status'] == 'queued'
    store.update(job['id'], status='transcribing')
    assert client.delete(path, headers=auth()).status_code == 409
    store.update(job['id'], status='done', result=json.dumps({'text':'Delete me', 'segments':[], 'language':'en', 'source':'test'}))
    password = (store.DATA / 'ACCESS.txt').read_text().split('Website password: ')[1].splitlines()[0]
    assert client.post('/api/login', json={'password':password}, headers={'x-transcript-request':'1'}).status_code == 200
    assert client.delete(path).status_code == 403
    assert client.delete(path, headers={'x-transcript-request':'1'}).json()['deleted']
    assert client.get(path).status_code == 404
    assert client.get(path+'/download').status_code == 404
    assert client.delete(path, headers={'x-transcript-request':'1'}).status_code == 404
    assert all(item['id'] != job['id'] for item in client.get('/api/jobs').json())
    replacement = store.create_job(url=url)
    assert replacement['id'] != job['id']  # Deleted results cannot be cache hits.
    store.update(replacement['id'], status='error')
    assert client.delete('/api/jobs/'+replacement['id'], headers=auth()).status_code == 200
    client.post('/api/logout', headers={'x-transcript-request':'1'})

def test_sensevoice_reprocesses_legacy_unformatted_cache():
    import hashlib
    url = 'https://www.instagram.com/p/LegacySenseTest/'
    legacy = store.create_job(url=url, model='sensevoice')
    old_key = hashlib.sha256(json.dumps([url, 'auto', 'sensevoice', True]).encode()).hexdigest()
    with store.connect() as db:
        db.execute("UPDATE jobs SET cache_key=?,status='done' WHERE id=?", (old_key, legacy['id']))
    fresh = store.create_job(url=url, model='sensevoice')
    assert fresh['id'] != legacy['id']
    assert store.get_job(legacy['id'])['status'] == 'done'
    assert store.create_job(url=url, model='sensevoice')['id'] == fresh['id']

@pytest.mark.parametrize('captions', [True, False])
def test_description_saved_for_caption_and_audio_results(client, monkeypatch, captions):
    import engine, yt_dlp, io
    description = 'Original description.\n\n#tag <script>literal text</script>'
    class Downloader:
        def __init__(self, options): self.options=options
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, *args, **kwargs):
            return {'title':'Description test','description':description,'duration':2,
                    'subtitles':{'en':[{'ext':'vtt','url':'https://example.test/captions'}]}}
        def urlopen(self, url): return io.BytesIO(b'WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello there.\n')
        def add_progress_hook(self, hook): pass
        def process_info(self, info):
            Path(self.options['outtmpl'].replace('%(ext)s','wav')).write_bytes(b'test audio')
    monkeypatch.setattr(yt_dlp, 'YoutubeDL', Downloader)
    monkeypatch.setattr(engine, 'transcribe', lambda *a: {'segments':[{'start':0,'end':2,'text':'Hello there.'}], 'language':'en', 'source':'test model'})
    job=store.create_job(url='https://www.youtube.com/watch?v=TestDesc123',captions=captions)
    engine.run(job['id'])
    result=client.get('/api/jobs/'+job['id'],headers=auth()).json()['result']
    assert result['description']==description and result['description_status']=='available'
    expected='Transcript:\n\nHello there.\n\nDescription:\n\n'+description
    assert result['formatted_text']==expected
    assert client.get('/api/jobs/'+job['id']+'/download',headers=auth()).text==expected
    assert app.get_transcript(job['id'])['description']==description
    assert app.get_transcript(job['id'])['text']=='Hello there.'
    assert description not in client.get('/api/jobs/'+job['id']+'/download?format=srt',headers=auth()).text

def test_description_missing_states():
    assert 'uploaded file' in store.format_output({'text':'Hello','description':'','description_status':'not_applicable'})
    assert 'No public description available.' in store.format_output({'text':'Hello','description':'','description_status':'unavailable'})
    assert 'older transcript' in store.format_output({'text':'Hello'})
