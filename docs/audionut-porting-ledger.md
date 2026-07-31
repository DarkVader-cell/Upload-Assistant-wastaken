# Audionut → Wastaken porting ledger

This is the working migration ledger for the Wastaken fork. It compares the
previous fork's `master` branch (`8f7b2480358a6e77407848bd7969c581fecdc242`)
with this fork's `wastaken` branch at the time of review. The old fork's
Windows-client branch and Web UI feature work are intentionally excluded from
this pass.

Each case must be reviewed independently. A case is not considered ported
until the behavior is implemented in this fork, covered by a focused test, and
marked `implemented` here. Live configuration, credentials, cookies, sessions,
logs, and host-specific Docker state are never porting inputs.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| `review` | Candidate identified; behavior comparison is still required. |
| `present` | Wastaken already provides the behavior; do not duplicate it. |
| `partial` | The concept exists, but important behavior or integration differs. |
| `missing` | The behavior is absent and is a candidate for a later port. |
| `conflict` | The old behavior does not fit Wastaken's architecture without a design decision. |
| `excluded` | Deliberately outside this migration pass. |
| `implemented` | Ported, tested, and documented in this fork. |

## Case-by-case ledger

### Metadata, naming, and media behavior

| ID | Case | Old-fork evidence | Wastaken evidence | Initial status | Recommendation / test gate |
| --- | --- | --- | --- | --- | --- |
| M-01 | Indian/South Asian streaming services and aliases | `src/region.py`, `docs/streaming-services.md`, commits `a63eca48`, `40db429d` | `src/region.py`, `docs/streaming-services.md` | `implemented` | Added missing aliases and documented the canonical codes; Ruff and stubbed runtime smoke checks pass. Formal pytest is pending dependency availability. |
| M-02 | Uppercase service abbreviations and SonyLIV recognition | commits `b0eb797f`, `97cb152b` | `src/region.py`, `tests/test_region_services.py` | `implemented` | Added separator-insensitive, case-insensitive SonyLIV detection while preserving `iP`, `iT`, and `iQIYI`; Ruff and stubbed runtime smoke checks pass. |
| M-03 | Bengali, Odia, and Punjabi language equivalence | `src/languages.py`, DT-related commits | `src/trackers/common.py` | `implemented` | Extended Wastaken's existing shared language-equivalence groups with Bengali/Bangla, Punjabi/Panjabi, and Odia/Oriya aliases. The old DT-only gate remains separate because DT is not present in this fork. |
| M-04 | Screenshot SAR/PAR correction and exact dimensions | `src/takescreens.py`, `src/screenshot_review.py` | `src/takescreens.py`, screenshot review support | `implemented` | Added the old fork's ≤4 px rounding snap rule across DVD, regular, and fallback screenshot filters; meaningful anamorphic corrections still emit scale filters. |
| M-05 | Fried.Chicken.Please release-group handling | `src/tags.py`, commit `7b1642bb` | `src/tags.py` | `implemented` | Canonicalized the dotted group before Wastaken's length guard; added a focused regression test. |
| M-06 | Anime recognition and duplicate-size tolerance | `src/tmdb.py`, `src/dupe_checking.py`, `src/trackers/ULCX.py` | `src/tmdb.py`, `src/dupe_checking.py` | `present` | Wastaken already contains the tightened Japanese-production anime detection, manual MAL preservation, and configurable duplicate-size percentage tolerance. No port required. |
| M-07 | VOD title parsing, scene search, HDR detection, and title normalization | `src/get_name.py`, `src/metadata_searching.py`, `src/tmdb.py`, commits `5fb7878e`, `9f9588e2` | corresponding Wastaken metadata modules | `review` | Port only measurable regressions; preserve Wastaken naming abstractions and add fixture tests. |
| M-08 | Go BDInfo integration | `bin/bdinfo-go/`, `src/bdinfo_comparator.py`, commit `c96590a3` | `src/bdinfo_comparator.py`, Docker binary tooling | `partial` | Verify binary discovery and output compatibility; test mocked BDInfo output and fallback behavior. |
| M-09 | DVD menu parsing and automatic bounded menu capture | `src/disc_menus.py`, `upload.py`, commits `8d15cfb1`, `e57fca5a` | `src/disc_menus.py`, upload pipeline | `review` | Compare menu-frame bounds, blank filtering, persistence, and screenshot separation. |
| M-10 | AITHER duplicate-language audio gate | `src/trackers/AITHER.py`, commit `e57fca5a` | `src/trackers/UNIT3D/aither.py` | `partial` | Adapt to Wastaken tracker layout; test commentary, Compatibility, and duplicate-language cases. |
| M-11 | DT Indian-language audio gate | `src/trackers/DT.py`, commits `3df90b9e`, `0ca8a461` | Wastaken tracker set | `review` | Determine whether DT exists or whether the rule belongs in a shared tracker layer; test `require_both`. |
| M-12 | OE/ULCX skip when streaming service is undetected | tracker modules and commit `314d5630` | `src/trackers/UNIT3D/onlyencodes.py`, `ulcx.py` | `partial` | Compare current guards and category behavior; add tracker-level regression tests. |
| M-13 | Description footer/signature policy | `upload.py`, description builder changes | `src/get_desc.py`, `upload.py` | `review` | Verify automatic footer behavior and preserve explicit/tracker signatures only. |
| M-14 | Safe path boundaries and literal glob escaping | `src/discparse.py`, `src/get_desc.py`, `src/manualpackage.py`, `src/rehostimages.py` | corresponding Wastaken modules | `review` | Port security fixes only where absent; test special characters and traversal-like names. |

### Queue, Qui, and unattended operation

| ID | Case | Old-fork evidence | Wastaken evidence | Initial status | Recommendation / test gate |
| --- | --- | --- | --- | --- | --- |
| Q-01 | Named queue safety and unattended no-prompt behavior | `src/queue_policy.py`, `src/queuemanage.py` | `src/queue_policy.py`, `src/queuemanage.py`, `tests/test_queue_policy.py` | `implemented` | Centralized the policy and guarded new/existing queue edit prompts; Ruff/static smoke checks pass, while formal pytest remains pending dependency availability. |
| Q-02 | FIFO detached Qui queue and unique session IDs | `web_ui/server.py`, `docs/detached-metadata.md`, commits `64fb32e9`, `ce3fdfe3` | current Wastaken server/API | `review` | Include API/worker behavior but exclude frontend presentation; test concurrent submissions and FIFO ordering. |
| Q-03 | Qui status and log endpoints | old fork `/api/qui/*` implementation and docs | current server API | `review` | Port only missing curl-friendly contracts; add endpoint contract tests with API-key authentication. |
| Q-04 | Detached metadata checkpoints and resume | `src/manual_metadata.py`, `web_ui/server.py`, `docs/detached-metadata.md` | current metadata/queue architecture | `review` | Reconcile with Wastaken’s job model; test waiting, validated resume, and invalid IDs. |
| Q-05 | `--prompt-missing-ids`, `--no-prompt-missing-ids`, and `--imdb-optional` | `src/args.py`, `src/prep.py`, `src/manual_metadata.py` | current CLI and metadata modules | `review` | Port CLI semantics independently from the Web UI; test IMDb-only, TMDb-only, and unattended cases. |
| Q-06 | TMDb contribution drafts | `src/tmdb_contribution.py`, old docs | current metadata modules | `review` | Treat as manual-review functionality; never auto-submit; test evidence and January-1 fallback labeling. |
| Q-07 | Preserved subprocess stdin and queue continuation | `upload.py`, queue commits | current `upload.py`, queue modules | `review` | Verify pipe ownership and failure isolation before porting; test child prompt and subsequent queue item. |
| Q-08 | Credential redaction and renamed-release policy | `cogs/redaction.py`, `src/safe_url.py`, `upload.py` | `cogs/redaction.py`, upload pipeline | `partial` | Compare coverage for URLs, headers, cookies, and sensitive keys; test redaction and escape hatch. |

### Trackers and tracker metadata

| ID | Case | Old-fork evidence | Wastaken evidence | Initial status | Recommendation / test gate |
| --- | --- | --- | --- | --- | --- |
| T-01 | Zenith / ZNTH | `src/trackers/ZNTH.py`, `src/trackersetup.py`, commits `c6165f1d`, `54007da6` | `src/trackers/UNIT3D/znth.py`, tracker registry | `present` | Confirm behavior and tests; do not duplicate the tracker. |
| T-02 | MTEAM and NexusPHP additions | `src/trackers/MTEAM.py`, `LAJIDUI.py`, `LPT.py`, `PTCAFE.py`, `PTFANS.py`, `PTGTK.py`, `RPT.py` | `src/trackers/mteam.py`, `src/trackers/NEXUSPHP/*` | `present` | Wastaken already provides these trackers in its own class layout; do not duplicate them. |
| T-03 | Tracker-specific category, banned-group, and ID fixes | old tracker modules and commits through `04271bb1` | Wastaken tracker modules | `review` | Create one subcase per tracker; each requires a focused fixture or mocked request test. |
| T-04 | HUNO 2026 API | `src/trackers/HUNO.py`, commit `da8fe7fe` | no obvious matching Wastaken module in current tracker tree | `missing` | Port as a Wastaken-compatible tracker only if HUNO is in scope; add API mock tests. |
| T-05 | MTV timeout and upload fixes | `src/trackers/MTV.py`, commits `70d1ace9`, `11cb5366` | no matching Wastaken MTV module visible | `missing` | Port only if MTV support is required; isolate timeout and request-shape changes. |
| T-06 | Tracker registration and display-name consistency | `src/trackersetup.py`, Python display map and config template | Wastaken `src/trackersetup.py`, config generator | `review` | Use Wastaken’s registry as the single source; do not create a duplicate JS map. |

### Image hosts and screenshot reliability

| ID | Case | Old-fork evidence | Wastaken evidence | Initial status | Recommendation / test gate |
| --- | --- | --- | --- | --- | --- |
| I-01 | Central image-host registry and tracker rules | `src/image_hosts.py`, `src/tracker_rules.py` | no matching registry files in current Wastaken tree | `missing` | Port as a cohesive capability; test config validation and tracker acceptance. |
| I-02 | Partial screenshot failover and cooldown health | `src/image_host_health.py`, `src/uploadscreens.py` | `src/uploadscreens.py` only | `partial` | Port state and retry semantics without changing Wastaken upload contracts; test partial success. |
| I-03 | Uploaded-image hash/URL cache | `src/uploaded_image_cache.py`, `src/rehostimages.py` | no matching cache module visible | `missing` | Port only after image-host registry shape is settled; test cache reuse and expiry. |
| I-04 | Lostimg and PTPImg policy | `src/uploadscreens.py`, config template, tracker rules | current image host support | `review` | Retain legacy URL acceptance while excluding PTPImg from new upload choices; test policy filtering. |
| I-05 | BeyondHD CDN stripping and host order | `upload.py`, config, image rehosting fixes | current upload/rehost pipeline | `review` | Compare actual tracker acceptance; test BHD-only versus non-BHD uploads. |
| I-06 | Screenshot worker/thread limits | `data/example-config.py`, `src/takescreens.py` | current screenshot defaults | `review` | Port only if Wastaken defaults are unsafe; test config defaults and worker invocation. |

### Docker, Gluetun, persistence, and CI

| ID | Case | Old-fork evidence | Wastaken evidence | Initial status | Recommendation / test gate |
| --- | --- | --- | --- | --- | --- |
| D-01 | Permanent container through `gluetun_seeding` | `Dockerfile`, `docker-compose.yml`, `docker-entrypoint.sh`, commits `c45e3078`–`1f377451` | local runtime compose and Wastaken Docker docs | `partial` | Keep the local deployment overlay separate from tracked source; document any upstream-compatible changes. |
| D-02 | Mounted config/session persistence | `web_ui/auth.py`, Docker volume setup, commit `dc2383e4` | current auth and Docker data paths | `partial` | Preserve the working local mounts; port source behavior only if upstream image loses state. |
| D-03 | Docker build stages, architecture binaries, and cache optimization | old `Dockerfile` and CI workflows | Wastaken Docker workflow | `review` | Compare build correctness and maintenance cost; port only functional or material reliability improvements. |
| D-04 | Branch/tag publishing and stale-image guards | old CI workflows and `ua` helper | Wastaken sync/release workflows | `review` | Keep deployment behavior local unless it belongs in the fork; test workflow YAML statically. |
| D-05 | Self-hosted runner DNS and digest cleanup | old Docker workflow | Wastaken workflow | `review` | Port only runner-specific reliability fixes; do not commit host DNS configuration. |
| D-06 | Upstream development synchronization | old sync workflows | `.github/workflows/sync-wastaken.yml` | `present` | Retain Wastaken’s hourly sync workflow and review conflicts manually. |

### Documentation and tests

| ID | Case | Old-fork evidence | Wastaken evidence | Initial status | Recommendation / test gate |
| --- | --- | --- | --- | --- | --- |
| R-01 | Migration guidance and local customization rules | old `CLAUDE.md`, `AGENTS.md`, migration inventory | Wastaken repository docs | `missing` | Add this ledger and document future local changes without copying secrets. |
| R-02 | Regression and smoke tests for selected ports | old `tests/`, `tests/smoke_test.sh` | current Wastaken tests | `review` | Port tests alongside each approved case; do not port tests for excluded features. |
| R-03 | Removed Discord integration | old fork history | Wastaken current tree | `excluded` | Do not reintroduce it. |

## Review order

The first implementation candidates should be reviewed in this order:

1. `T-02` and `T-03`: tracker behavior and tracker additions that Wastaken does not already contain.
2. `Q-01` through `Q-03`: Qui, queue, and unattended execution contracts.
3. `M-01` through `M-03`: metadata, streaming-service, and language behavior.
4. `I-01` through `I-03`: image-host reliability as one coherent subsystem.
5. `D-01` through `D-03`: only source-level Docker changes that are not already solved by the local deployment overlay.

Each case will be handled as a separate change with its own diff, focused tests,
runtime verification where applicable, and ledger update.
