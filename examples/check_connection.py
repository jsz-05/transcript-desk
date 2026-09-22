"""Read-only MCP connection check. Python 3.10+; no third-party packages."""
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    base = os.environ.get('TRANSCRIPT_DESK_URL', '').rstrip('/')
    token = os.environ.get('TRANSCRIPT_DESK_TOKEN', '')
    parsed = urlparse(base)
    local = parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')
    if (not token or not parsed.hostname or (parsed.scheme != 'https' and not local)
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/')):
        raise RuntimeError('Set TRANSCRIPT_DESK_URL to the HTTPS origin (or loopback HTTP) and TRANSCRIPT_DESK_TOKEN to the agent token.')
    opener = build_opener(NoRedirect)
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
               'Accept': 'application/json, text/event-stream'}

    def rpc(method, params=None, request_id=None):
        payload = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            payload['params'] = params
        if request_id is not None:
            payload['id'] = request_id
        request = Request(base + '/mcp/', data=json.dumps(payload).encode(), headers=headers)
        with opener.open(request, timeout=30) as response:
            raw = response.read()
        if request_id is None:
            return None
        data = json.loads(raw)
        if 'error' in data or 'result' not in data:
            raise RuntimeError('MCP request failed; check server logs privately.')
        return data['result']

    result = rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                               'clientInfo': {'name': 'transcript-desk-check', 'version': '1.0'}}, 1)
    headers['MCP-Protocol-Version'] = result['protocolVersion']
    rpc('notifications/initialized')
    names = {tool['name'] for tool in rpc('tools/list', {}, 2)['tools']}
    expected = {'transcribe_url', 'get_transcription_status', 'get_transcript'}
    if not expected.issubset(names):
        raise RuntimeError('Connected, but expected Transcript Desk tools are missing.')
    print('Connected: HTTPS/HTTP authentication and MCP initialization passed.')
    print('Tools: ' + ', '.join(sorted(expected)))
    print('No job was submitted. Configure Codex separately and verify its tool discovery too.')


if __name__ == '__main__':
    try:
        main()
    except HTTPError as exc:
        print(f'HTTP {exc.code}: check endpoint and agent token.', file=sys.stderr)
        raise SystemExit(1)
    except (URLError, TimeoutError):
        print('Connection failed: check Tailscale, server availability and TLS.', file=sys.stderr)
        raise SystemExit(1)
    except (RuntimeError, ValueError, KeyError) as exc:
        print(str(exc) if isinstance(exc, RuntimeError) else 'Unexpected MCP response.', file=sys.stderr)
        raise SystemExit(1)
