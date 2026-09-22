# Transcript Desk

A small, private transcription website and MCP server for a Windows home server. Paste a YouTube or Instagram URL, or upload audio/video, and get the full transcript. No summaries, rewriting, paid transcription API, or LLM service is involved.

The server first tries existing subtitles. If none are usable, it downloads audio (or the available video) and transcribes locally with Whisper Base fast using faster-whisper INT8. The interface provides history, deletion of finished/failed jobs, copying, TXT and SRT exports; the HTTP API also exports JSON. The browser and agents share the same durable queue and saved results. Website output, Copy text and TXT exports use `Transcript:` and `Description:` sections. Descriptions are the original platform metadata retrieved with the video, not AI-generated summaries. Missing/private descriptions are marked unavailable; uploads have no platform description. SRT remains speech-only. JSON and MCP retain raw transcript text and expose the description separately.

**Already have a running server?** Start with the [Mac quick-start and Codex handoff](docs/MAC-QUICKSTART.md). The Mac only needs client access, not another server installation. See [MCP/API details](docs/MCP.md) for agent behavior and authentication.

## Architecture and defaults

```text
Mac browser / locally running MCP client
       | HTTPS over your private Tailscale network
Tailscale Serve on the Windows server
       | HTTP on loopback, port 8765
FastAPI + authentication + SQLite + MCP
       | one queued job at a time
Resident worker: YouTube subtitles OR yt-dlp -> Whisper Base fast CPU INT8
```

| Setting | Default / behavior |
| --- | --- |
| Model | Whisper Base fast INT8, kept loaded; beam size 1, best-of 1 |
| Alternatives | Standard Whisper Base (beam 5), Small, SenseVoice |
| Language | Automatically detected |
| Subtitles | Enabled; creator captions, then automatic captions, then audio |
| CPU inference | Four threads by default, one worker, below-normal Windows priority |
| GPU | Not used |
| Active work | One recording at a time, at most 20 pending/active jobs |
| Limits | 300 MiB media, three-hour recording, six-hour processing timeout |
| Agent access | Single shared bearer token; all authenticated users see the same jobs |

SenseVoice uses its native punctuation and text normalization; no separate rewriting model runs. Its speed and recognition quality vary by recording, and Whisper Base can be a better choice for English reels and names. SenseVoice automatically detects English, Chinese, Cantonese, Japanese and Korean. The language selector sets the caption preference; SenseVoice audio recognition always detects the language. Base fast always uses multilingual Base, including when English is selected. Standard Base and Small use their `.en` variants when English is selected. Translated subtitle tracks are skipped. Speech recognition and automatic captions can make mistakes; the app preserves their returned text. SenseVoice SRT timestamps mark speech segments, not precise word alignment.

Completed and in-progress URL requests with identical URL, model, language and subtitle settings reuse the same job. Change a setting to create a separate comparison. There is no forced-refresh button yet. File uploads always create a new job.

## Windows installation from a fresh clone

Tested host: Windows x64, Python 3.12, Ryzen 5 PRO 2400GE, 16 GB RAM. The Mac is a client and does not need Python, Node, the models, or this repository. These scripts target Windows; Linux/macOS server deployment is not tested. Allow several GB of free disk for dependencies, models and working files.

1. Install [Python 3.12 x64](https://www.python.org/downloads/windows/), [Node.js LTS](https://nodejs.org/en/download), [Git for Windows](https://git-scm.com/download/win), and [Tailscale](https://tailscale.com/download/windows). Use a normal desktop Python installation, preferably for all users if installing the service. Node supplies yt-dlp's YouTube JavaScript runtime. Install the [Microsoft Visual C++ x64 redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) if native Python modules report missing DLLs. Open a new PowerShell window afterward.
2. Clone this repository into a permanent folder that is not synchronized by OneDrive/Dropbox. Sign into GitHub with an account that can access the private repository:

   ```powershell
   git clone https://github.com/jsz-05/transcript-desk.git
   Set-Location .\transcript-desk
   ```

3. Run setup:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\Setup.ps1
   ```

   This creates `.venv`, installs pinned Python dependencies, initializes `data/`, downloads Whisper Base from Hugging Face, and downloads the official WinSW 2.12.0 service wrapper with a SHA-256 check. It creates the local service XML from the checked-in template. It does not install the service, change sleep settings, or publish a network endpoint. No administrator access is required for this step. The execution-policy override lasts only for this PowerShell process.

   If the `py` launcher is unavailable, specify Python directly:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\Setup.ps1 -Python 'C:\Path\To\Python312\python.exe'
   ```

   `-SkipModels` defers the Base download until model loading. Optional Whisper models download on first use. To enable the optional SenseVoice backend on a new installation, run `.\.venv\Scripts\python.exe .\prepare_sensevoice.py`. `-SkipServiceWrapper` omits the wrapper if using only foreground operation. Stop the running app before rerunning setup; database initialization requeues interrupted jobs.

4. Start locally:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\Start-Local.ps1
   ```

5. Open **http://127.0.0.1:8765/** on the server. Open `data\ACCESS.txt` locally and use the **Website password** to sign in. The separate **Agent API token** is for programmatic clients. Store both in a password manager; do not commit this file or paste tokens into agent conversations.
6. Submit a short recording as a local check. This foreground server stops when its terminal closes. Install the service below for unattended operation.

The decoding library PyAV includes the media libraries needed by this workflow; a separate ffmpeg executable is not required for the selected single-file audio/video format. Site extraction behavior can change and may need a future yt-dlp update.

## Private HTTPS and access from other Wi-Fi networks

1. Open Tailscale on the Windows server and sign in. Use the same identity on the Mac later.
2. From the repository folder, run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\Connect-Private.ps1
   ```

3. If Tailscale prints an enablement URL, open it and enable HTTPS/Serve. Leave optional public Funnel access off. Complete the consent page, then rerun the script if the first command did not finish.
4. The script prints the private website and MCP URLs and saves the website address in `data\private-url.txt`. Use the actual printed name, not the example names in these docs.
5. Verify on the server:

   ```powershell
   & 'C:\Program Files\Tailscale\tailscale.exe' serve status
   ```

   Expect `https://YOUR-PC.YOUR-TAILNET.ts.net (tailnet only)` forwarding `/` to `http://127.0.0.1:8765`.

`Connect-Private.ps1` checks Tailscale login, writes the app's permitted hostnames, sets Tailscale unattended mode, and configures `serve --bg --https=443`. Closing that setup terminal does not stop Serve. Run as administrator if Tailscale reports a permission error. Serve persists independently of the app; a working proxy still needs the Python server running. No router port forwarding or public domain purchase is needed.

HTTPS certificates publish the hostname in standard public certificate-transparency logs, but Serve keeps access restricted to your Tailscale network and access rules. The application password/token is a separate layer of authentication. Do not use `tailscale funnel` or change the Python listener to `0.0.0.0` for this setup.

### On a MacBook

1. Install [Tailscale for macOS](https://tailscale.com/download/mac).
2. Open it and follow the prompts to install/allow the VPN configuration.
3. Sign in with the same identity used on the Windows server.
4. Check that Tailscale is connected. Leave Exit Node set to None.
5. In Safari or Chrome, open the private HTTPS URL printed by the server setup script.
6. Enter the website password saved from `data/ACCESS.txt` and bookmark the page.

The Mac can use another Wi-Fi network or a hotspot. It stays on that network; Tailscale provides an encrypted private route to the server. Ordinary internet traffic keeps using the Mac's existing connection when no exit node is selected. Both machines must be online. The Windows server must be awake and the app must be running. To verify remote access, repeat the test while the Mac is on a hotspot.

Tailscale Personal currently covers this non-commercial setup for free. Consult [current pricing](https://tailscale.com/pricing) for limits rather than assuming they never change. There are no transcription-minute fees in this app; your internet/electricity costs still apply. Some networks require a slower relay path. Device keys can expire and require sign-in; review [key expiry](https://tailscale.com/docs/features/access-control/key-expiry) before relying on unattended access.

## Automatic startup after Windows boots

Complete a successful local test first. Keep the repository and Python runtime in their permanent locations. The service references them directly; moving/deleting them will break startup.

1. Stop the foreground app with Ctrl+C. The installer can also stop a Python process whose command line contains this repository's absolute `app.py` path, but refuses to kill an unrecognized listener on port 8765.
2. Open PowerShell **as administrator**, change to this repository, and run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\Install-Startup.ps1
   ```

3. Check:

   ```powershell
   Get-Service TranscriptDesk, Tailscale
   & 'C:\Program Files\Tailscale\tailscale.exe' serve status
   ```

4. Check the website, then perform a planned Windows reboot and verify the website from the Mac before depending on unattended recovery.

The installer creates a delayed automatic WinSW service as `NT AUTHORITY\LocalService`, grants it read/execute access to the application and Python/Node runtime directories, and grants modify access to `data/`. Only trusted users should be able to edit the application's code. It sets the AC sleep timeout to Never and saves the prior timeout in `data/power-before.txt`. Other power settings and BIOS settings are unchanged. It records the discovered Node path in the ignored local service XML. The wrapper restarts the app after a failure.

This starts the app when Windows boots. Automatically powering on after electricity is restored is a separate BIOS setting, if supported by the PC. A sleeping or powered-off server is unavailable.

Maintenance commands, from an administrator PowerShell:

```powershell
Restart-Service TranscriptDesk
Stop-Service TranscriptDesk
Start-Service TranscriptDesk
```

To remove app startup, stop the service and run `./TranscriptDeskService.exe uninstall` from the repository. Restore your desired AC sleep timeout with `powercfg /change standby-timeout-ac MINUTES`. To stop private HTTPS forwarding separately, use `tailscale serve --https=443 off`. This does not erase transcripts or uninstall Tailscale.

## CPU concurrency and model memory

A [two-versus-four-thread comparison](docs/PERFORMANCE.md) on the original server reduced mean waiting by about 28% for both models on a 59-second clip.

Speech inference defaults to **four threads**, bounded by the machine's logical CPU count. One recording runs at a time with below-normal process priority. Four inference threads is not a hard 50% CPU cap on an eight-thread CPU: decoding, VAD, library helper threads, physical cores and SMT scheduling affect actual usage.

To choose another thread count for a foreground server, set the variable before starting it:

```powershell
$env:TRANSCRIPT_CPU_THREADS = '2'
powershell -ExecutionPolicy Bypass -File .\Start-Local.ps1
```

For a Windows service, edit the `TRANSCRIPT_CPU_THREADS` value in the ignored root `TranscriptDeskService.xml`, then restart the service as administrator. The checked-in template sets it to 4 for new installations. Values must be positive integers; values above the machine's logical CPU count are clamped. This setting applies to SenseVoice and both Whisper models. It does not change model selection or enable concurrent jobs. The worker sets its own OpenMP thread limit from the same setting, so an old `OMP_NUM_THREADS` value does not override it.

Whisper Base loads once when the app starts and stays in a separate worker process between jobs. It consumes RAM while idle but does not continuously transcribe or poll the microphone. Other model choices load only when selected and can temporarily use additional RAM alongside Base.

Use **Unload model** at the top of the website to pause new work and release the worker's memory. An active job finishes first. The website, saved transcripts and downloads remain available. New submissions stay queued, including subtitle requests. **Load model** reloads Whisper Base and resumes the queue. The app remembers this setting across restarts. Model files stay on disk; Windows may also retain reclaimable filesystem cache. Unloading terminates the worker, releasing any retained inference-library allocations too.

Audio results expose `cpu_threads`, `model_load_seconds`, and `transcribe_seconds`. For resident Base fast, `model_load_seconds` is zero because startup occurred before the job, and `model_resident` is true. `elapsed_seconds` measures the job, excluding queue time. SenseVoice streams decoded audio through VAD with bounded segments to avoid holding an entire recording in RAM.

## Agent connections: MCP and HTTP

See **[docs/MCP.md](docs/MCP.md)** for the full protocol, tool parameters, lifecycle, chunking, authentication, Codex configuration, and Python examples. See **[examples/transcribe.py](examples/transcribe.py)** for an executable HTTP client that submits a link, polls and writes the full raw transcript to stdout.

The MCP endpoint is `https://YOUR-PC.YOUR-TAILNET.ts.net/mcp/` (keep the trailing slash). It uses Streamable HTTP and the Agent API token, not the website password. A client must be able to reach the private URL. Installing Tailscale on a Mac makes it reachable to local Mac software; it does not automatically provide network access to a cloud-hosted agent. No public/cloud bridge is installed by this repository.

Endpoint defaults are `base-fast`, language auto, subtitles enabled. REST clients can also request `base`, `small` or `sensevoice`. The MCP `transcribe_url` tool has no model parameter and uses Base fast. Browser WebMCP tools use the browser's selected model and language; these are separate from the remote MCP server.

## Files, storage and privacy

| Path | Purpose | In Git? |
| --- | --- | --- |
| `app.py`, `engine.py`, `store.py`, `static/` | Application source | Yes |
| `service/TranscriptDeskService.xml` | Portable service template | Yes |
| Root `TranscriptDeskService.xml` | Generated local service configuration | No |
| `data/ACCESS.txt`, `data/auth.json` | Generated credentials and authentication hashes | No |
| `data/jobs.sqlite3*` | Job history, transcript text and browser sessions | No |
| `data/models/`, `data/hf/`, `data/yt-cache/` | Downloaded model/extractor caches | No |
| `data/media/`, `data/uploads/` | Temporary downloaded/uploaded media | No |
| `data/network.json`, `data/private-url.txt` | Host-specific connection details | No |
| `data/logs/`, `data/worker.log` | Operational logs | No |
| `.venv/`, service executable, `comparison/` | Dependencies and local test artifacts | No |

The download prefers audio-only when available. The downloader checks the 300 MiB limit if the size is known and monitors downloaded bytes otherwise; it can exceed the boundary by a download chunk before aborting. Uploads are size-checked too. Transcripts are saved on the server until deleted. Right-click a finished or failed sidebar entry, choose Delete transcript, then confirm to permanently remove its history and saved text. Deleted URLs can be submitted again as new jobs; queued/running jobs cannot be deleted. Existing exported files and external backups are unaffected. Normal job completion/failure removes downloaded media and the server's upload copy. Your original source file is untouched. Forced termination or power failure can leave temporary files; no startup cleanup sweep is implemented. Logs and saved transcripts do not have automatic retention limits yet.

Only one app process may access the job queue as a worker. Startup marks interrupted jobs queued, so do not import `app.py` against live production data from a second process or start two servers. Whisper Base stays resident until unloaded from the website. First-use Whisper downloads add time.

This is a single-user private-network utility, not an audited multi-tenant public service. Every valid API token/browser session has full access to this app's transcripts and queue. Site URLs are limited to HTTPS YouTube/Instagram individual posts/videos; creator login cookies are not imported. URLs still contact those platforms, and model downloads contact GitHub (SenseVoice/VAD) or Hugging Face (Whisper). File transcription runs locally after model download. Private GitHub visibility does not replace credential exclusion.

### Backups, recovery and credential rotation

Stop the app/service before backing up `data/` to encrypted private storage. The database, `auth.json`, and any plaintext `ACCESS.txt` backup are sensitive. Models can be downloaded again. A Git clone restores code only, not passwords or transcripts.

If credentials leak: stop the app, move `data/auth.json` and `data/ACCESS.txt` to a protected location outside the repository, and remove existing sessions using this command from the repository with the app stopped:

```powershell
.\.venv\Scripts\python.exe -c "import store; db=store.connect(); db.execute('DELETE FROM sessions'); db.commit(); db.close()"
```

Start the app to generate a fresh password/token. Update clients and securely dispose of the old credential copies. Rotating the token alone does not invalidate existing browser sessions unless the sessions table is cleared. Do not publish credentials in Git and then rely on a later deletion; prior commits retain them.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Local page fails | Start the app; inspect `data/worker.log` or the foreground terminal |
| HTTPS fails but local page works | Tailscale signed in on both devices, `serve status`, server awake, correct URL |
| 502 from private URL | Serve is running but the Python app is stopped/unreachable |
| 400 Unknown host | Rerun `Connect-Private.ps1` after a device/tailnet rename |
| 401 from API/MCP | Supply the Agent API token, not the website password; no token in query strings |
| MCP OAuth prompt | This server uses a configured bearer token, not OAuth discovery/login |
| Codex says token variable missing | Fully restart the client with that environment variable available to its process |
| Instagram/YouTube blocked | Platform may require login or rate-limit; upload a saved file you can access |
| Model unavailable / queued jobs paused | Check the model panel, check model download errors in the worker log, then click Load model |
| Service cannot read Python/Node | Check install path and LocalService permissions; use a normal all-users runtime |
| Port 8765 already occupied | Stop the existing instance; do not run foreground and service simultaneously |

## Development and validation

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

Tests use an isolated temporary database and disable the worker; they do not download media or contact third-party sites. They cover authentication, CSRF/host checks, URL validation, caching, exports, transcript chunk reconstruction, caption overlap, and MCP tool discovery/lifecycle. Live site behavior is a separate integration check.

Historical Whisper measurements on the 2400GE with two inference threads: an 11-second sample took 24.94 seconds with Small and 9.23 seconds with Base. One Instagram clip took 55.55 seconds with Small and 28 seconds with Base. A YouTube caption fetch took 3.48 seconds. These are single-run end-to-end measurements, not guaranteed performance or a formal accuracy evaluation. Automated tests and these live tests passed on the original host. The owner also confirmed access from a Mac over Tailscale. A clean-machine service install still needs separate verification.

Before updating, stop the service, back up data, inspect source/dependency changes, install updated requirements and run tests, then start the service and check local/private access. The generated service XML and all private data remain untracked. Inspect `git status` and `git diff --cached` before every push; never force-add ignored credentials, transcripts or models.

## References

- [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve)
- [Tailscale Mac installation](https://tailscale.com/docs/install/mac)
- [SenseVoice](https://github.com/FunAudioLLM/SenseVoice)
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [WinSW 2.12.0](https://github.com/winsw/winsw/releases/tag/v2.12.0)
- [MCP transport specification](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)

Third-party dependencies and downloaded model weights retain their own licenses; they are not included in this repository.