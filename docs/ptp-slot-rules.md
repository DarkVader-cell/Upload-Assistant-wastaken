# PTP coexistence checks

The PTP rules engine implements the operator-supplied October 2026 rules
snapshot. It is a coexistence recommendation and content gate, not proof that a
release meets every PTP upload rule. Site rules and staff decisions remain
authoritative.

## Data and decisions

PTP searches retain **every torrent in the group**, including other quality
bands, source/codec/container, edition, Not Main Movie, size and MediaInfo.
Failed or malformed group lookups/inventories skip PTP rather than treating the
failure as an empty group. Other selected trackers continue independently.

- **ALLOW**: a supported slot appears vacant. It is not quality approval.
- **BLOCK**: prohibited content, exact release, SD WEB with an HD equivalent, or
  HDR UHD WEB after an HDR Blu-ray UHD encode. Ordinary duplicate/force prompts
  do not override these decisions.
- **REVIEW**: unknown traits, occupied slots, comparisons, content eligibility or
  staff approval. Unattended uploads stop at REVIEW, even with no basic dupes.
  Attended confirmation explicitly asks whether the required evidence and staff
  approval have been checked; it defaults to No.

Actual recognized cuts have independent slots. Distributor, Criterion and
remaster labels do not manufacture additional cuts. Unrecognized cut claims
need human review, rather than assuming a new slot. Extras and Open Matte have
separate treatment; Open Matte needs OAR comparisons and correct form flags.
Encode retention/quality size differences (20%, or 40% for SD) are guidelines:
filesize alone never authorizes a second encode or an automatic trump.

## UHD clarification

SDR contains neither HDR nor DV. DV Profile 5 has no HDR10 base layer and must
be positively identified; a bare DV label is insufficient. HDR10-compatible DV
does not create a third HDR10 encode slot. SDR and HDR10 encodes each have two
quality/retention positions; Profile 5 is separate. WEB vacancy is separated by
these dynamic-range classes, not by provider. **Once an HDR Blu-ray UHD encode
exists for the same cut, no further HDR UHD WEB upload is allowed**, even with
comparisons. An SDR Blu-ray encode does not trigger that HDR prohibition.

SDR 1080p HEVC WEB still requires exhaustive AVC comparisons and superior
picture quality. Unknown DV profiles and unsupported HDR formats require
review. Bandwidth waits refresh PTP's group inventory; newly conflicting or
review-required releases do not silently pass a basic duplicate filter.

## Limits

Staff approval, real picture quality, source authenticity, official-vs-fan edit
provenance, unaltered reports, subtitles, posters, screenshot coverage and
blacklist changes cannot all be established from names or API fields. Explicit
metadata can detect some prohibited cases (ordinary TV, Adult, prerelease
sources, MP4 requiring remux, archives, declared transcodes/fan edits/AI dubs),
but a missing declaration is not proof of compliance. Verify those remaining
requirements before uploading. UA never fabricates approval or automatically
trumps another release from size alone.

`DEFAULT.slot_rules = False` disables the slot engine. This is a broad operator
override, not a statement that an upload complies with PTP rules. Search errors
still do not establish vacancy.
