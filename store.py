"""Durable jobs and single-user authentication. No external database."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('TRANSCRIPT_DATA', ROOT / 'data'))
DATA.mkdir(parents=True, exist_ok=True)

def connect():
    db = sqlite3.connect(DATA / 'jobs.sqlite3', timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    return db

def initialize():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, cache_key TEXT, url TEXT, title TEXT, status TEXT,
          progress REAL DEFAULT 0, message TEXT DEFAULT '', source TEXT,
          language TEXT, model TEXT, captions INTEGER, input_path TEXT,
          created REAL, updated REAL, result TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, expires REAL);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        db.execute("UPDATE jobs SET status='queued', message='Resuming after restart' WHERE status IN ('working','downloading','transcribing')")
    secret_path = DATA / 'auth.json'
    if not secret_path.exists():
        password, api_key, salt = secrets.token_urlsafe(18), secrets.token_urlsafe(32), secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
        secret_path.write_text(json.dumps({'salt': salt, 'password_hash': digest, 'api_hash': hashlib.sha256(api_key.encode()).hexdigest()}), encoding='utf-8')
        (DATA / 'ACCESS.txt').write_text(f'Transcript Desk — private credentials\n\nWebsite password: {password}\nAgent API token: {api_key}\n\nKeep this file private. Your browser uses the password; agents use the API token.\n', encoding='utf-8')

def verify_password(password):
    auth = json.loads((DATA / 'auth.json').read_text())
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(auth['salt']), 600000).hex()
    return hmac.compare_digest(digest, auth['password_hash'])

def verify_api(token):
    auth = json.loads((DATA / 'auth.json').read_text())
    return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), auth['api_hash'])

def new_session():
    token = secrets.token_urlsafe(32)
    with connect() as db:
        db.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))
        db.execute('INSERT INTO sessions VALUES (?,?)', (hashlib.sha256(token.encode()).hexdigest(), time.time() + 86400 * 14))
    return token

def valid_session(token):
    if not token:
        return False
    with connect() as db:
        return db.execute('SELECT 1 FROM sessions WHERE token=? AND expires>?', (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone() is not None

def end_session(token):
    with connect() as db:
        db.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(token.encode()).hexdigest(),))

def get_job(job_id):
    with connect() as db:
        row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
    return dict(row) if row else None

def public_job(row, include_result=False):
    result = {k: v for k, v in row.items() if k not in ('input_path', 'cache_key', 'result')}
    if include_result:
        result['result'] = json.loads(row['result']) if row['result'] else None
        if result['result'] is not None:
            result['result']['formatted_text'] = format_output(result['result'])
    return result

def format_output(result):
    description = result.get('description')
    if not description:
        status = result.get('description_status', 'not_saved')
        description = {'not_applicable': 'No description — uploaded file.',
                       'unavailable': 'No public description available.',
                       'not_saved': 'Description was not saved for this older transcript.'}.get(status, 'No public description available.')
    return f"Transcript:\n\n{result['text']}\n\nDescription:\n\n{description}"

def update(job_id, **values):
    permitted = {'status', 'progress', 'message', 'source', 'title', 'result', 'error', 'input_path'}
    assert set(values) <= permitted
    values['updated'] = time.time()
    with connect() as db:
        db.execute('UPDATE jobs SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?', (*values.values(), job_id))

def model_enabled():
    with connect() as db:
        row = db.execute("SELECT value FROM settings WHERE key='model_enabled'").fetchone()
    return not row or row['value'] == 'true'

def set_model_enabled(enabled):
    with connect() as db:
        db.execute("INSERT INTO settings(key,value) VALUES ('model_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ('true' if enabled else 'false',))

def create_job(url='', title='', language='auto', model='base-fast', captions=True, input_path=''):
    cache_settings = [url, language, model, captions]
    if model == 'sensevoice':
        # Keep old transcripts visible, but don't return pre-fix unformatted
        # results when the user requests a transcription after this update.
        cache_settings.append('sensevoice-itn-v2')
    cache = hashlib.sha256(json.dumps(cache_settings).encode()).hexdigest() if url else None
    now = time.time()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if cache:
            existing = db.execute("SELECT * FROM jobs WHERE cache_key=? AND status IN ('queued','working','downloading','transcribing','done') ORDER BY created DESC LIMIT 1", (cache,)).fetchone()
            if existing:
                return public_job(dict(existing))
        count = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','working','downloading','transcribing')").fetchone()[0]
        if count >= 20:
            raise ValueError('The queue is full. Wait for a job to finish.')
        job_id = secrets.token_hex(12)
        db.execute('INSERT INTO jobs (id,cache_key,url,title,status,language,model,captions,input_path,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)', (job_id, cache, url, title or url, 'queued', language, model, int(captions), input_path, now, now))
    return public_job(get_job(job_id))
