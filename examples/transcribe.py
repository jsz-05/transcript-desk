"""Authenticated REST client. Requires Python 3.10+; no extra packages."""
import argparse
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a bearer token to a redirected destination.
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', help='YouTube or Instagram video URL')
    parser.add_argument('--model', choices=('base-fast', 'sensevoice', 'base', 'small'), default='base-fast')
    parser.add_argument('--language', default='auto')
    parser.add_argument('--no-subtitles', action='store_true')
    args = parser.parse_args()
    base = os.environ.get('TRANSCRIPT_DESK_URL', '').rstrip('/')
    token = os.environ.get('TRANSCRIPT_DESK_TOKEN', '')
    parsed = urlparse(base)
    local = parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')
    if not token or not parsed.hostname or (parsed.scheme != 'https' and not local):
        parser.error('Set TRANSCRIPT_DESK_URL to the HTTPS app URL (or loopback HTTP) and TRANSCRIPT_DESK_TOKEN to the agent token.')
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        parser.error('TRANSCRIPT_DESK_URL must be the app origin, without a path, credentials, query or fragment.')
    opener = build_opener(NoRedirect)

    def request(path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        with opener.open(Request(base + path, data=body, headers=headers), timeout=60) as response:
            return json.load(response)

    job = request('/api/jobs', {'url': args.url, 'model': args.model,
                               'language': args.language, 'captions': not args.no_subtitles})
    deadline = time.monotonic() + 7 * 3600
    while time.monotonic() < deadline:
        job = request('/api/jobs/' + job['id'])
        if job['status'] == 'done':
            print(job['result'].get('formatted_text', job['result']['text']))
            return
        if job['status'] == 'error':
            raise RuntimeError(job.get('error') or 'Transcription failed')
        time.sleep(5)
    raise RuntimeError('Client wait timed out; the server job may still be queued or running.')


if __name__ == '__main__':
    try:
        main()
    except HTTPError as exc:
        print(f'HTTP {exc.code}: check the endpoint, credentials and job settings.', file=sys.stderr)
        raise SystemExit(1)
    except (URLError, TimeoutError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
