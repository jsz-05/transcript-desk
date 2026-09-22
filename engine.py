"""Caption retrieval followed by bounded CPU transcription in a child process."""
import gc
import html
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
import store

def validate_url(value):
    value = value.strip()
    parsed = urlparse(value)
    host = (parsed.hostname or '').lower()
    allowed = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be', 'instagram.com', 'www.instagram.com'}
    if parsed.scheme != 'https' or host not in allowed or parsed.username or parsed.password or parsed.port:
        raise ValueError('Use an HTTPS YouTube video or Instagram reel/post link.')
    if host.endswith('youtube.com'):
        video_id = parse_qs(parsed.query).get('v', [''])[0] if parsed.path == '/watch' else (parsed.path.split('/')[2] if re.match(r'^/(shorts|live|embed)/', parsed.path) else '')
    elif host == 'youtu.be':
        video_id = parsed.path.strip('/').split('/')[0]
    else:
        match = re.fullmatch(r'/(reel|reels|p|tv)/([A-Za-z0-9_-]+)/?', parsed.path)
        if not match:
            raise ValueError('Use a link to an individual Instagram reel or post.')
        return f'https://www.instagram.com/{match[1]}/{match[2]}/'
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        raise ValueError('Use a link to an individual YouTube video, not a channel or playlist.')
    return f'https://www.youtube.com/watch?v={video_id}'

def caption_segments(payload, extension):
    segments = []
    if extension == 'json3':
        for event in json.loads(payload).get('events', []):
            text = ''.join(s.get('utf8', '') for s in event.get('segs', [])).strip()
            if text:
                start = event.get('tStartMs', 0) / 1000
                segments.append({'start': start, 'end': start + event.get('dDurationMs', 0) / 1000, 'text': html.unescape(text)})
    else:
        def seconds(value):
            parts = value.replace(',', '.').split(':')
            return sum(float(p) * 60 ** i for i, p in enumerate(reversed(parts)))
        for block in re.split(r'\n\s*\n', payload.replace('\r', '')):
            match = re.search(r'(\d[\d:.]+) --> (\d[\d:.]+)[^\n]*\n(.*)', block, re.S)
            if match:
                text = html.unescape(re.sub(r'<[^>]*>', '', match[3])).strip()
                if text:
                    segments.append({'start': seconds(match[1]), 'end': seconds(match[2]), 'text': text})
    # Rolling captions repeat words in overlapping cues; keep non-overlapping repetitions.
    cleaned = []
    for segment in segments:
        words = segment['text'].split()
        if cleaned and segment['start'] <= cleaned[-1]['end'] + 0.05:
            previous = cleaned[-1]['text'].split()
            for n in range(min(len(previous), len(words)), 0, -1):
                if previous[-n:] == words[:n]:
                    words = words[n:]
                    break
        if words:
            cleaned.append({**segment, 'text': ' '.join(words)})
    return cleaned

def srt(segments):
    def stamp(t):
        ms = max(0, round(t * 1000))
        return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
    return '\n\n'.join(f"{i}\n{stamp(s['start'])} --> {stamp(s['end'])}\n{s['text']}" for i, s in enumerate(segments, 1)) + '\n'

def retrieve(job, directory):
    import yt_dlp
    node = os.environ.get('TRANSCRIPT_NODE_PATH') or shutil.which('node')
    # Optional adjacent runtime layout; normal installations use Node from PATH.
    bundled_node = Path(sys.base_prefix).parent / 'node' / 'bin' / 'node.exe'
    node = node or (str(bundled_node) if bundled_node.exists() else None)
    options = {'quiet': True, 'no_warnings': True, 'noplaylist': True, 'socket_timeout': 25,
               'retries': 2, 'extractor_retries': 1, 'cachedir': str(store.DATA / 'yt-cache'),
               'max_filesize': 300 * 1024 * 1024, 'format': 'bestaudio/best',
               'outtmpl': str(directory / 'media.%(ext)s'), 'restrictfilenames': True,
               'concurrent_fragment_downloads': 1}
    if node:
        options['js_runtimes'] = {'node': {'path': node}}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(job['url'], download=False)
        if info.get('_type') in ('playlist', 'multi_video'):
            raise ValueError('This link contains multiple videos. Upload the individual video instead.')
        store.update(job['id'], title=info.get('title') or job['url'])
        if (info.get('duration') or 0) > 10800 or info.get('is_live'):
            raise ValueError('Use a finished video up to three hours long.')
        if job['captions']:
            preferred = job['language'] if job['language'] != 'auto' else (info.get('language') or 'en')
            for kind, label in [('subtitles', 'Creator captions'), ('automatic_captions', 'Automatic captions')]:
                tracks = info.get(kind) or {}
                languages = [lang for lang in tracks if lang == preferred or lang.split('-')[0] == preferred.split('-')[0]]
                languages.sort(key=lambda lang: (lang != preferred, 'orig' not in lang, lang))
                for lang in languages:
                    formats = sorted(tracks[lang], key=lambda t: t.get('ext') != 'json3')
                    for track in formats:
                        if track.get('ext') not in ('json3', 'vtt') or not track.get('url'):
                            continue
                        # Do not silently use machine-translated subtitle tracks.
                        if parse_qs(urlparse(track['url']).query).get('tlang'):
                            continue
                        try:
                            with ydl.urlopen(track['url']) as response:
                                payload = response.read(16 * 1024 * 1024).decode('utf-8')
                            segments = caption_segments(payload, track['ext'])
                            if segments:
                                return {'segments': segments, 'language': lang, 'source': label}, None
                        except Exception:
                            continue
            store.update(job['id'], message='No usable captions found. Downloading audio.', status='downloading')
        else:
            store.update(job['id'], status='downloading', message='Downloading audio')
        def progress(data):
            if data.get('downloaded_bytes', 0) > 300 * 1024 * 1024:
                raise ValueError('This media exceeds the 300 MB download limit.')
        ydl.add_progress_hook(progress)
        # Reuse metadata instead of making a second extraction request.
        ydl.process_info(info)
        media = list(directory.glob('media.*'))
        media = [p for p in media if p.suffix not in ('.part', '.ytdl')]
        if not media:
            raise ValueError('The website did not return a downloadable video. Try uploading the file.')
        return None, media[0]

def transcribe(job, path):
    import av
    with av.open(str(path)) as container:
        if container.duration and container.duration / av.time_base > 10800:
            raise ValueError('Use a recording up to three hours long.')
        if not container.streams.audio:
            raise ValueError('This file has no audio track.')
    from faster_whisper import WhisperModel
    model_name = job['model'] + ('.en' if job['language'] == 'en' else '')
    store.update(job['id'], status='transcribing', message='Loading speech model (first use may download it)', progress=0)
    local_model = store.DATA / 'models' / model_name
    model = WhisperModel(str(local_model) if (local_model / 'model.bin').exists() else model_name, device='cpu', compute_type='int8', cpu_threads=2, num_workers=1, download_root=str(store.DATA / 'models'))
    iterator, info = model.transcribe(str(path), language=None if job['language'] == 'auto' else job['language'], task='transcribe', beam_size=5, vad_filter=True, vad_parameters={'min_silence_duration_ms': 1000}, word_timestamps=False)
    segments = []
    store.update(job['id'], message='Transcribing speech')
    for segment in iterator:
        segments.append({'start': round(segment.start, 3), 'end': round(segment.end, 3), 'text': segment.text.strip()})
        store.update(job['id'], progress=min(99, 100 * segment.end / max(info.duration, 1)))
    del model
    gc.collect()
    return {'segments': segments, 'language': info.language, 'source': f'Local Whisper {model_name}'}

def run(job_id):
    import psutil
    try:
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 5)
    except (psutil.Error, AttributeError):
        pass
    job = store.get_job(job_id)
    directory = store.DATA / 'media' / job_id
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        store.update(job_id, status='working', message='Checking available captions' if job['url'] and job['captions'] else 'Preparing audio')
        if job['url']:
            result, media = retrieve(job, directory)
        else:
            result, media = None, Path(job['input_path'])
        if result is None:
            result = transcribe(job, media)
        result['text'] = '\n'.join(s['text'] for s in result['segments'])
        result['elapsed_seconds'] = round(time.monotonic() - started, 2)
        store.update(job_id, status='done', progress=100, source=result['source'], result=json.dumps(result, ensure_ascii=False), message='Transcript ready')
    except Exception as exc:
        message = re.sub(r'\x1b\[[0-9;]*m', '', str(exc))[:700]
        if any(s in message.lower() for s in ('sign in', 'login', 'cookies', 'bot', '403', '429')):
            message = 'The website blocked this request or requires sign-in. Try again later, or upload a saved audio/video file. ' + message[:250]
        store.update(job_id, status='error', error=message, message='Could not complete transcription')
    finally:
        # Only per-job generated paths under our data directory are removed.
        if directory.parent.resolve() == (store.DATA / 'media').resolve():
            shutil.rmtree(directory, ignore_errors=True)
        if job['input_path']:
            uploaded = Path(job['input_path'])
            if uploaded.parent.resolve() == (store.DATA / 'uploads').resolve():
                uploaded.unlink(missing_ok=True)
        store.update(job_id, input_path='')

if __name__ == '__main__':
    run(sys.argv[1])
