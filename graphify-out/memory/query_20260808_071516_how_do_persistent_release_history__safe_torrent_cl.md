---
type: "query"
date: "2026-08-08T07:15:16.019387+00:00"
question: "How do persistent release history, safe torrent-client removal, screenshot refill, full-disc duplicate checks, and Luminarr encoder rules connect to the upload and Web UI workflows?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["ReleaseHistoryStore", "refill_screenshot_slot", "DupeChecker", "Luminarr"]
---

# Q: How do persistent release history, safe torrent-client removal, screenshot refill, full-disc duplicate checks, and Luminarr encoder rules connect to the upload and Web UI workflows?

## Answer

Upload and detached Qui jobs persist compact outcomes through ReleaseHistoryStore for the history API and Operations UI. Torrent-client deletion repairs dependent defaults and lists atomically. Screenshot refill preserves the selected slot and target count. Structured tracker evidence feeds full-disc duplicate classification without encode-only resolution/HDR filtering. Luminarr preflight enforces the configured x264/x265 resolution and HDR rules before upload.

## Outcome

- Signal: useful

## Source Nodes

- ReleaseHistoryStore
- refill_screenshot_slot
- DupeChecker
- Luminarr