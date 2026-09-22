"""Own the resident inference process, so unloading actually releases its RAM."""
import asyncio
import json
import os
import sys
import subprocess
import psutil
import store


class ModelRuntime:
    def __init__(self):
        self.enabled = store.model_enabled()
        self.process = None
        self.log = None
        self.state = 'starting' if self.enabled else 'unloaded'
        self.error = ''
        self.busy = False
        self.lock = asyncio.Lock()

    def status(self):
        alive = self.process is not None and self.process.returncode is None
        if self.state == 'ready' and not alive:
            self.state = 'starting' if self.enabled else 'unloaded'
        return {'enabled': self.enabled, 'state': self.state, 'busy': self.busy,
                'loaded': alive and self.state in ('ready', 'busy', 'unloading'),
                'error': self.error, 'model': 'Whisper Base fast INT8'}

    async def set_enabled(self, enabled):
        store.set_model_enabled(enabled)
        self.enabled = enabled
        self.error = ''
        if not enabled:
            self.state = 'unloading'
            # A running request holds the lock; finish it before releasing RAM.
            if not self.lock.locked():
                async with self.lock:
                    await self._stop()
        elif not self.process or self.process.returncode is not None:
            self.state = 'starting'
        elif self.busy:
            self.state = 'busy'
        else:
            self.state = 'ready'
        return self.status()

    async def _stop(self):
        if self.process:
            if self.process.returncode is None:
                # Windows venv python.exe may be a redirector with a real Python
                # child. Release the entire private worker tree, not just its stub.
                try:
                    descendants = psutil.Process(self.process.pid).children(recursive=True)
                except psutil.NoSuchProcess:
                    descendants = []
                for child in reversed(descendants):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                try:
                    self.process.kill()
                except ProcessLookupError:
                    pass
                if descendants:
                    await asyncio.to_thread(psutil.wait_procs, descendants, timeout=5)
            await self.process.wait()
        self.process = None
        if self.log:
            self.log.close()
        self.log = None
        self.state = 'starting' if self.enabled else 'unloaded'

    async def _read(self, timeout):
        try:
            line = await asyncio.wait_for(self.process.stdout.readline(), timeout)
        except TimeoutError:
            raise RuntimeError('Speech worker timed out. Use Load model to retry.') from None
        if not line:
            raise RuntimeError('Speech worker stopped. Check data/worker.log; use Load model to retry.')
        message = json.loads(line)
        if message.get('error'):
            raise RuntimeError(message['error'])
        return message

    async def _start(self):
        await self._stop()
        self.state = 'starting'
        self.log = open(store.DATA / 'worker.log', 'ab', buffering=0)
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, '-u', str(store.ROOT / 'engine.py'), '--resident',
            cwd=str(store.ROOT), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=self.log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        await self._read(120)
        self.state = 'ready'
        self.error = ''

    async def ensure_loaded(self):
        async with self.lock:
            if not self.enabled:
                await self._stop()
                return
            try:
                if not self.process or self.process.returncode is not None:
                    await self._start()
            except Exception as exc:
                await self._stop()
                self.state = 'error'
                self.error = str(exc)
                raise
            finally:
                if not self.enabled:
                    await self._stop()

    async def run_job(self, job_id):
        async with self.lock:
            if not self.enabled:
                return False
            self.busy = True
            try:
                if not self.process or self.process.returncode is not None:
                    await self._start()
                # Unload may have been requested while the model was loading.
                if not self.enabled:
                    return False
                self.state = 'busy'
                self.process.stdin.write((json.dumps({'job_id': job_id})+'\n').encode())
                await self.process.stdin.drain()
                await self._read(6 * 3600)
                return True
            except Exception as exc:
                await self._stop()
                self.state = 'error'
                self.error = str(exc)
                store.update(job_id, status='error', error=str(exc), message='Transcription interrupted')
                return True
            finally:
                self.busy = False
                if not self.enabled:
                    await self._stop()
                elif self.process and self.process.returncode is None:
                    self.state = 'ready'

    async def close(self):
        async with self.lock:
            await self._stop()
