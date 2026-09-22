# Two versus four CPU inference threads

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

Loading took about 0.6–0.8 seconds for Base and 1.8–2.1 seconds for Small in these runs. A resident model could save startup/loading time, but speech processing dominates this clip. The application keeps on-demand loading and releases the worker after each job.

The application now defaults to four inference threads for both models. It still processes one job at a time at below-normal priority. This is a concurrency setting, not a strict CPU-utilization ceiling. Use TRANSCRIPT_CPU_THREADS to tune it. See the README for foreground and service configuration.
