# Audionut → Wastaken porting ledger

This is the working migration ledger for the Wastaken fork. It tracks reviewed
behavior from the previous fork, current Wastaken development, relevant UpBrr
changes, Web UI/Qui integration, Docker/runtime work, and current tracker rules.
Entries describe the evidence reviewed at implementation time; upstream changes
remain subject to the normal sync and conflict-review process.

Each case must be reviewed independently. A case is not considered ported
until the behavior is implemented in this fork, covered by a focused test, and
marked `implemented` here. Live configuration, credentials, cookies, sessions,
logs, and host-specific Docker state are never porting inputs.

Latest validation (2026-08-08): the complete Python suite passes, changed-file
Ruff and frontend ESLint pass, the architecture guard remains within all three
limits, Docker builds and reaches its internal health check, and no tracked
features or files were deleted.

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
| M-01 | Indian/South Asian streaming services and aliases | `src/region.py`, `docs/streaming-services.md`, commits `a63eca48`, `40db429d` | `src/region.py`, `docs/streaming-services.md` | `implemented` | Added missing aliases and documented the canonical codes; Ruff and the complete Python suite pass. |
| M-02 | Uppercase service abbreviations and SonyLIV recognition | commits `b0eb797f`, `97cb152b` | `src/region.py`, `tests/test_region_services.py` | `implemented` | Added separator-insensitive, case-insensitive SonyLIV detection while preserving `iP`, `iT`, and `iQIYI`; Ruff and stubbed runtime smoke checks pass. |
| M-03 | Bengali, Odia, and Punjabi language equivalence | `src/languages.py`, DT-related commits | `src/trackers/common.py` | `implemented` | Extended Wastaken's existing shared language-equivalence groups with Bengali/Bangla, Punjabi/Panjabi, and Odia/Oriya aliases. The old DT-only gate remains separate because DT is not present in this fork. |
| M-04 | Screenshot SAR/PAR correction and exact dimensions | `src/takescreens.py`, `src/screenshot_review.py` | `src/takescreens.py`, screenshot review support | `implemented` | Added the old fork's ≤4 px rounding snap rule across DVD, regular, and fallback screenshot filters; meaningful anamorphic corrections still emit scale filters. |
| M-05 | Fried.Chicken.Please release-group handling | `src/tags.py`, commit `7b1642bb` | `src/tags.py` | `implemented` | Canonicalized the dotted group before Wastaken's length guard; added a focused regression test. |
| M-06 | Anime recognition and duplicate-size tolerance | `src/tmdb.py`, `src/dupe_checking.py`, `src/trackers/ULCX.py` | `src/tmdb.py`, `src/dupe_checking.py` | `present` | Wastaken already contains the tightened Japanese-production anime detection, manual MAL preservation, and configurable duplicate-size percentage tolerance. No port required. |
| M-07 | VOD title parsing, scene search, HDR detection, and title normalization | `src/get_name.py`, `src/metadata_searching.py`, `src/tmdb.py`, commits `5fb7878e`, `9f9588e2` | `src/get_name.py`, `src/video.py` | `partial` | Added VOD/VODRip parsing and codec/year normalization plus case-insensitive HDR/DV detection. The old narrow SRRDB TV query depends on helpers absent from Wastaken and remains deferred for a separate review. |
| M-08 | Go BDInfo integration | `bin/bdinfo-go/`, `src/bdinfo_comparator.py`, commit `c96590a3` | `bin/get_bdinfo.py`, `bin/get_bdinfo_docker.py`, `src/discparse.py`, `Dockerfile` | `present` | Wastaken already downloads autobrr/go-bdinfo per platform, bundles it in Docker, and invokes it with playlist/report arguments. The old custom wrapper would be redundant. |
| M-09 | DVD menu parsing and automatic bounded menu capture | `src/disc_menus.py`, `upload.py`, commits `8d15cfb1`, `e57fca5a` | `src/disc_menus.py`, `upload.py`, `src/uploadscreens.py` | `present` | Wastaken already has automatic DVD menu capture with bounded selection, blank-frame filtering, persistence, fallback sampling, and normal-screenshot separation. No port required. |
| M-10 | AITHER duplicate-language audio gate | `src/trackers/AITHER.py`, commit `e57fca5a` | `src/trackers/UNIT3D/aither.py` | `implemented` | Adapted the gate to Wastaken's typed Meta structure; commentary tracks remain exempt, while duplicate primary-language audio requires a Compatibility title. |
| M-11 | DT/DesiTorrents Indian-language audio gate and banned groups | `src/trackers/DT.py`, commits `3df90b9e`, `0ca8a461`, current tracker rule supplied 2026-08-08 | `src/trackers/UNIT3D/torrentdesi.py`, `src/trackersetup.py` | `implemented` | Preserves the existing bans and adds YTS, RARBG, BonsaiHD, GalaxyRG, `-=!DrSTAR!=-`, AKG, and DUS. Listed-group WEB-DLs require an explicit confirmation that they contain no advertisement tags or watermarks; unattended runs remain conservative. |
| M-13 | UpBrr Blu-ray/disc duplicate fixes | UpBrr `7f8130fc` | `src/discparse.py`, `src/dupe_checking.py`, ANT/HDB/AZ adapters | `implemented` | Ported standalone-summary reuse, bounded malformed-report handling, structured candidate evidence, full-disc classification, incomplete file-count handling, and authoritative full-disc matching that bypasses encode-only resolution/HDR filters. |
| M-14 | BLU banned-group refresh | Current tracker rule supplied 2026-08-08 | `src/trackers/UNIT3D/blutopia.py` | `implemented` | BLU now matches all 95 supplied banned groups exactly; AOC, CMRG, EVO, TERMiNAL, and exact-case ViSION are limited to raw content, leading release-tag dashes are normalized, and AOC requires explicit approval. |
| M-15 | LUME accepted encoder rules | Current tracker rules 6.5.4.1–6.5.4.3 supplied 2026-08-08 | `src/trackers/UNIT3D/luminarr.py` | `implemented` | Encodes below 1080p require x264. Live-action 1080p SDR requires x264, while live-action 1080p HDR/DV/HLG requires x265; animation and non-encode behavior is unchanged. |
| M-12 | OE/ULCX skip when streaming service is undetected | tracker modules and commit `314d5630` | `src/trackers/UNIT3D/onlyencodes.py`, `ulcx.py` | `implemented` | Added the WEBDL/WEBRip empty-service guard to both trackers so unattended uploads cannot proceed without a streaming-service tag. |
| M-16 | Description footer/signature policy | `upload.py`, description builder changes | `src/get_desc.py`, tracker description writers | `implemented` | Removed the automatic Upload Assistant signature from the shared builder and tracker-specific writers; `custom_signature` configuration remains available. |
| M-17 | Safe path boundaries and literal glob escaping | `src/discparse.py`, `src/get_desc.py`, `src/manualpackage.py`, `src/rehostimages.py` | corresponding Wastaken modules | `present` | Wastaken's pathlib-based paths avoid the old glob construction hazards, and `rehostimages.py` already escapes title/disc-derived glob patterns. No port required. |

### Queue, Qui, and unattended operation

| ID | Case | Old-fork evidence | Wastaken evidence | Initial status | Recommendation / test gate |
| --- | --- | --- | --- | --- | --- |
| Q-01 | Named queue safety and unattended no-prompt behavior | `src/queue_policy.py`, `src/queuemanage.py` | `src/queue_policy.py`, `src/queuemanage.py`, `tests/test_queue_policy.py` | `implemented` | Centralized the policy and guarded new/existing queue edit prompts; Ruff and the complete Python suite pass. |
| Q-02 | FIFO detached Qui queue and unique session IDs | `web_ui/server.py`, `docs/detached-metadata.md`, commits `64fb32e9`, `ce3fdfe3` | `web_ui/server.py` | `implemented` | Added authenticated detached FIFO processing with unique token-based job IDs, unattended subprocess execution, and isolated per-job logs. |
| Q-03 | Qui status and log endpoints | old fork `/api/qui/*` implementation and docs | `web_ui/server.py` | `implemented` | Added authenticated `/api/qui/status` and `/api/qui/log/<job_id>` contracts with bounded log-tail responses. |
| Q-04 | Detached metadata checkpoints and resume | `src/manual_metadata.py`, `web_ui/server.py`, `docs/detached-metadata.md` | `src/manual_metadata.py`, `web_ui/server.py`, `src/prep_helpers.py` | `implemented` | Detached jobs now emit a structured missing-ID checkpoint, expose it in status, validate IMDb/TMDb submissions, and resume the same subprocess through its stdin pipe. Compile, Ruff, and focused normalization smoke checks pass. |
| Q-05 | `--prompt-missing-ids`, `--no-prompt-missing-ids`, and `--imdb-optional` | `src/args.py`, `src/prep.py`, `src/manual_metadata.py` | `src/args.py`, `src/prep_helpers.py`, `src/manual_metadata.py` | `implemented` | Added the three CLI controls and applied them to interactive and detached metadata policy. IMDb-optional skips the missing-IMDb checkpoint when TMDb is present; no-prompt suppresses it. Compile, Ruff, and policy smoke checks pass. |
| Q-06 | TMDb contribution drafts | `src/tmdb_contribution.py`, old docs | current metadata modules | `review` | Treat as manual-review functionality; never auto-submit; test evidence and January-1 fallback labeling. |
| Q-07 | Preserved subprocess stdin and queue continuation | `upload.py`, queue commits | `web_ui/server.py`, `upload.py`, queue modules | `implemented` | Preserved the child stdin pipe for interactive continuation and stopped Web UI cleanup from closing stdout/stderr while reader threads drain them. Detached FIFO execution remains isolated per job; compile and Ruff checks pass. |
| Q-08 | Credential redaction and renamed-release policy | `cogs/redaction.py`, `src/safe_url.py`, `upload.py` | `cogs/redaction.py`, `src/safe_url.py`, `src/modified_release.py`, `src/takescreens.py`, `upload.py` | `implemented` | Expanded redaction across token paths, query parameters, headers, cookies, JSON keys, and long hex tokens; added private-network URL blocking and an unattended renamed-release guard with an explicit `allow_renamed_releases` escape hatch. Focused smoke checks pass. |

### Trackers and tracker metadata

| ID | Case | Old-fork evidence | Wastaken evidence | Initial status | Recommendation / test gate |
| --- | --- | --- | --- | --- | --- |
| T-01 | Zenith / ZNTH | `src/trackers/ZNTH.py`, `src/trackersetup.py`, commits `c6165f1d`, `54007da6` | `src/trackers/UNIT3D/znth.py`, tracker registry | `present` | Confirm behavior and tests; do not duplicate the tracker. |
| T-02 | MTEAM and NexusPHP additions | `src/trackers/MTEAM.py`, `LAJIDUI.py`, `LPT.py`, `PTCAFE.py`, `PTFANS.py`, `PTGTK.py`, `RPT.py` | `src/trackers/mteam.py`, `src/trackers/NEXUSPHP/*` | `present` | Wastaken already provides these trackers in its own class layout; do not duplicate them. |
| T-03 | Tracker-specific category, banned-group, and ID fixes | old tracker modules and commits through `04271bb1` | `src/trackers/greatposterwall.py` plus existing BJShare, ImmortalSeed, SeedPool, and PTP equivalents | `implemented` | Added GPW skip-state propagation when additional checks reject a release. The other audited fixes were already present or belonged to absent trackers; compile and Ruff checks pass. |
| T-04 | HUNO 2026 API | `src/trackers/HUNO.py`, commit `da8fe7fe` | `src/trackers/UNIT3D/hawkeuno.py`, registry, config template | `present` | Wastaken already provides the HAWKEUNO tracker with the 2026 `api_token` upload flow, multipart files, auto-mode fields, response handling, and registration. No port required. |
| T-05 | MTV timeout and upload fixes | `src/trackers/MTV.py`, commits `70d1ace9`, `11cb5366` | `src/trackers/morethantv.py` | `implemented` | Ported the 60-second upload, 30-second cookie/auth, and 20-second search timeouts to Wastaken’s MORETHANTV implementation. No request-shape changes were needed; compile and Ruff checks pass. |
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
| D-03 | Docker build stages, architecture binaries, and cache optimization | old `Dockerfile` and CI workflows | multi-stage `Dockerfile`, `.dockerignore`, entrypoint, and Wastaken CI | `implemented` | Dependency and per-architecture binary stages are cacheable independently; the final runtime excludes build tooling, tests, secrets, caches, and wrong-platform binaries. First-start config bootstrapping preserves existing mounts. |
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
