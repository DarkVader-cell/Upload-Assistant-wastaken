# Complementary Feature Roadmap

This backlog is intentionally separate from the behavior-preserving refactor. Scores use a five-point scale; higher workflow and performance scores are better, while lower risk and upstream-conflict scores are better.

| Rank | Feature | Workflow | Performance | Risk | Upstream conflict | Rationale |
| ---: | --- | ---: | ---: | ---: | ---: | --- |
| 1 | Content-addressed preparation artifacts | 5 | 5 | 3 | 2 | Reuse hashes, MediaInfo, screenshots, descriptions, and metadata across retries or multiple trackers. |
| 2 | Stage-level resumable queues | 5 | 4 | 3 | 2 | Resume after the last completed pipeline stage instead of restarting a release. |
| 3 | Dry-run execution planner | 5 | 3 | 2 | 1 | Show stages, cache hits, expected API calls, selected trackers, and estimated work before execution. |
| 4 | Adaptive provider and tracker scheduler | 4 | 5 | 4 | 2 | Use observed latency and rate-limit headers to maximize safe concurrency. |
| 5 | Provider/client health dashboard | 4 | 3 | 2 | 1 | Surface cache efficiency, API health, Qui status, client connectivity, and external-tool availability. |
| 6 | Stable extension/plugin API | 4 | 3 | 4 | 1 | Add trackers and metadata providers outside upstream-owned modules, sharply reducing merge conflicts. |
| 7 | Deeper Qui synchronization | 4 | 3 | 3 | 1 | Mirror queue state, progress, retry controls, and completion status through the existing optional native API. |
| 8 | Safe parallel queue preparation | 4 | 5 | 4 | 3 | Prepare independent releases concurrently while serializing prompts and tracker mutations. |

Recommended sequence: artifact reuse, stage checkpoints, dry-run planning, then adaptive scheduling. The plugin API should be designed alongside those features but introduced only after the tracker and provider contracts stabilize.
