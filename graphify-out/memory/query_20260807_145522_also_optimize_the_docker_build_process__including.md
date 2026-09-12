---
type: "query"
date: "2026-08-07T14:55:22.907432+00:00"
question: "Also optimize the docker build process, including the image size."
contributor: "graphify"
outcome: "useful"
source_nodes: ["Requirements"]
---

# Q: Also optimize the docker build process, including the image size.

## Answer

Replaced the single-stage python:3.14 image with cached python:3.14-slim stages for Python dependencies and architecture-specific helper downloads, then copied only runtime assets. Excluded host config, credentials, sessions, caches, Node modules, Graphify output, Docker data, tests, and Windows binaries from context. Added a dependency-free Python health check and CI runtime/size guards. AMD64 image fell from 3,150,404,000 to 1,335,580,195 bytes (57.61%); context transfer fell from 83.4 MB to 18.8 kB. Runtime, Web UI health, CLI, PUID/PGID, Compose, 480 tests, and ARM64 native wheel availability passed.

## Outcome

- Signal: useful

## Source Nodes

- Requirements