"""Stage pinned public SenseVoice/VAD files. No job database initialization."""
import hashlib
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request
import store

RELEASE = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/'
MODEL = 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17'

def prepare():
    target = store.DATA / 'models' / 'sensevoice'
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sensevoice-', dir=target.parent) as temporary:
        temporary = Path(temporary)
        if not all((target/name).exists() for name in ('model.int8.onnx', 'tokens.txt')):
            archive = temporary / 'model.tar.bz2'
            print('Downloading SenseVoice Small INT8…', flush=True)
            urllib.request.urlretrieve(RELEASE+MODEL+'.tar.bz2', archive)
            with tarfile.open(archive) as tf:
                # Read only the two expected regular files; never extract arbitrary paths.
                for name in ('model.int8.onnx', 'tokens.txt'):
                    member = tf.getmember(MODEL+'/'+name)
                    if not member.isfile(): raise ValueError('Unexpected model archive entry')
                    staged = temporary/name
                    with tf.extractfile(member) as src, staged.open('wb') as out:
                        shutil.copyfileobj(src, out)
                    staged.replace(target/name)
        if not (target/'silero_vad.onnx').exists():
            print('Downloading speech detector…', flush=True)
            staged = temporary/'silero_vad.onnx'
            urllib.request.urlretrieve(RELEASE+'silero_vad.onnx', staged)
            staged.replace(target/'silero_vad.onnx')
    print('SenseVoice files ready.')

if __name__ == '__main__': prepare()
