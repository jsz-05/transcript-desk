"""One resident SenseVoice model; bounded streaming audio and VAD segments."""
from collections import Counter
import re
import time
import store

LANGUAGES = {'auto', 'en', 'zh', 'yue', 'ja', 'ko'}

class SenseVoice:
    def __init__(self, threads):
        import sherpa_onnx
        self.sherpa = sherpa_onnx
        self.threads = threads
        folder = store.DATA / 'models' / 'sensevoice'
        for name in ('model.int8.onnx', 'tokens.txt', 'silero_vad.onnx'):
            if not (folder / name).exists():
                raise RuntimeError('SenseVoice files are missing. Run prepare_sensevoice.py or Setup.ps1, then click Load model.')
        self.folder = folder
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(folder / 'model.int8.onnx'), tokens=str(folder / 'tokens.txt'),
            # Native punctuation/text formatting is part of transcription,
            # not summarization. Disabling it produces lowercase run-on text.
            num_threads=threads, provider='cpu', language='auto', use_itn=True)

    def transcribe(self, job, path):
        import av
        import numpy as np
        if job['language'] not in LANGUAGES:
            raise ValueError('SenseVoice supports English, Chinese, Cantonese, Japanese and Korean. Choose a Whisper model for other languages.')
        config = self.sherpa.VadModelConfig()
        config.silero_vad.model = str(self.folder / 'silero_vad.onnx')
        config.silero_vad.min_silence_duration = .5
        config.silero_vad.min_speech_duration = .15
        config.silero_vad.max_speech_duration = 20
        config.sample_rate = 16000
        config.num_threads = 1
        detector = self.sherpa.VoiceActivityDetector(config, buffer_size_in_seconds=60)
        segments, languages = [], Counter()
        # VAD can identify speech slightly after a word starts. Keep a short
        # pre-roll, bounded by the previous segment to avoid repeating words.
        ring = np.zeros(40 * 16000, dtype=np.float32)
        fed, previous_end = 0, 0
        started = time.monotonic()
        store.update(job['id'], status='transcribing', message='Transcribing with SenseVoice', progress=0)
        def drain():
            nonlocal previous_end
            while not detector.empty():
                speech = detector.front
                samples = np.asarray(speech.samples, dtype=np.float32)
                padded_start = max(previous_end, speech.start - 6400, 0)
                if padded_start < speech.start:
                    prefix = ring[np.arange(padded_start, speech.start) % len(ring)]
                    samples = np.concatenate((prefix, samples))
                previous_end = speech.start + len(speech.samples)
                start = padded_start / 16000
                stream = self.recognizer.create_stream()
                stream.accept_waveform(16000, samples)
                self.recognizer.decode_stream(stream)
                result = stream.result
                text = re.sub(r'<\|[^|]+\|>', '', result.text).strip()
                lang = re.sub(r'<\||\|>', '', result.lang or '')
                if text:
                    segments.append({'start': round(start, 3), 'end': round(start+len(samples)/16000, 3), 'text': text})
                    if lang: languages[lang] += len(samples)
                detector.pop()
        with av.open(str(path)) as container:
            if not container.streams.audio:
                raise ValueError('This file has no audio track.')
            duration = container.duration / av.time_base if container.duration else None
            if duration and duration > 10800:
                raise ValueError('Use a recording up to three hours long.')
            resampler = av.AudioResampler(format='fltp', layout='mono', rate=16000)
            pending = np.empty(0, dtype=np.float32)
            count = 0
            def feed(frame):
                nonlocal pending, count, fed
                samples = frame.to_ndarray().reshape(-1)
                count += len(samples)
                if count > 10800*16000:
                    raise ValueError('Use a recording up to three hours long.')
                pending = np.concatenate((pending, samples))
                end = len(pending)//512*512
                for i in range(0, end, 512):
                    chunk = pending[i:i+512]
                    ring[np.arange(fed, fed+512) % len(ring)] = chunk
                    fed += 512
                    detector.accept_waveform(chunk)
                    drain()
                pending = pending[end:].copy()
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame): feed(converted)
                if duration and count % 16000 < 2048:
                    store.update(job['id'], progress=min(99, count/16000/duration*100))
            for converted in resampler.resample(None): feed(converted)
            if len(pending):
                detector.accept_waveform(np.pad(pending, (0, 512-len(pending))))
            detector.flush()
            drain()
        return {'segments': segments, 'language': languages.most_common(1)[0][0] if languages else job['language'],
                'source': 'Local SenseVoice Small INT8', 'cpu_threads': self.threads,
                'model_load_seconds': 0, 'model_resident': True,
                'transcribe_seconds': round(time.monotonic()-started, 2),
                'timestamp_precision': 'speech segments'}
