# Performance measurements

## Current configuration

The current default is resident Whisper Base fast INT8: four inference threads, beam size 1, best-of 1, one job at a time, below-normal worker priority. The model stays loaded until disabled in the UI. Standard Base/Small and SenseVoice are optional on-demand alternatives. Thread count is not a strict CPU-utilization ceiling; tune `TRANSCRIPT_CPU_THREADS` if needed. The historical measurements below use different decoding/model settings and should not be read as current default latency or an accuracy ranking.

## Two versus four CPU inference threads

Measured on a Ryzen 5 PRO 2400GE (4 cores / 8 logical threads), using a 58.99-second Instagram audio clip. Each run started a fresh worker at below-normal priority. The clip was downloaded once; the table excludes network retrieval and queue time but includes worker startup, model loading and speech processing. Models, INT8 precision, automatic language detection, VAD and beam size 5 stayed the same.

Two runs per configuration, with model/thread order reversed for the second pass. These are small-sample local measurements, not a general performance guarantee. Other desktop activity and operating-system caches can affect results.

| Model | 2 threads, mean | 4 threads, mean | Reduction in waiting |
| --- | ---: | ---: | ---: |
| Base | 22.3 s | 16.0 s | 28% |
| Small | 56.5 s | 40.5 s | 28% |

## Individual runs

| Model | Threads | Total worker seconds | Model load seconds | Speech seconds |
| --- | ---: | ---: | ---: | ---: |
| base | 2 | 24.07 | 0.62 | 22.27 |
| base | 4 | 16.58 | 0.83 | 14.66 |
| small | 2 | 55.28 | 1.75 | 52.55 |
| small | 4 | 40.93 | 1.84 | 37.95 |
| small | 4 | 40.09 | 1.81 | 37.08 |
| small | 2 | 57.74 | 2.05 | 54.56 |
| base | 4 | 15.52 | 0.66 | 13.8 |
| base | 2 | 20.58 | 0.67 | 18.81 |

Loading took about 0.6–0.8 seconds for Base and 1.8–2.1 seconds for Small in these runs. A resident model could save startup/loading time, but speech processing dominates this clip. These measurements predate the resident SenseVoice worker. That experimental SenseVoice default was subsequently replaced by resident Whisper Base fast after real-world quality comparisons.

## Historical resident SenseVoice integration check (2026-09-22)

On the same mini PC with four inference threads, a 9.3-second English recording took 1.39 seconds on its first resident transcription and 1.27 seconds on the next. The worker process was reused. The full worker process tree held approximately 389 MiB after those jobs; actual memory depends on audio and selected models.

A 37.2-second continuous test took 6.83 seconds and covered the recording through the final speech segment. Unload was requested while that job was active: the job completed, then the entire worker tree exited. A separate check confirmed that submissions remain queued while unloaded and resume after Load model. Model preferences survived creation of a new runtime. Both controls were also exercised in the running website.

These are integration smoke measurements, not a new accuracy benchmark or guaranteed latency. They exclude network download time and the initial model load. Twelve automated API, authentication, MCP, and runtime tests passed alongside these real-model checks.

See the README for current foreground and service configuration.
