# AnimeBytes transcode integration: status and required specification

AnimeBytes is **not currently implemented** in this fork's tracker registry.
There is no verified AnimeBytes torrent-upload API adapter or automatic
AnimeBytes transcode uploader. Existing Orpheus music upload support is not
AnimeBytes support, and a search/scrape API does not establish upload capability.

## Requested workflow

The reference project is [orpheusmorebetter](https://github.com/walkrflocka/orpheusmorebetter).
It finds missing Orpheus album formats, prepares FLAC/MP3 V0/V2/320 variants,
preserves audio tags, and can submit them to Orpheus. Its account crawler,
format/group identifiers and upload requests are Orpheus-specific; changing a
hostname is not an AnimeBytes implementation.

That project is GPLv3; this fork is UAPL. Do not vendor its modules into this
repository without resolving license compatibility. Evaluate a separately
installed tool interface or implement the necessary behavior independently.
Do not execute its default account-wide upload workflow as a test. Its
`--no-upload` mode is not by itself assurance against every remote mutation:
its separate 24-bit recategorization option also needs review.

## Documentation needed before implementing AB submission

Provide redacted, current AnimeBytes documentation covering:

- Whether torrent **uploads** have a supported API; authentication, scopes and
  rate limits. A search-only API is insufficient.
- Required endpoints, request fields, category/group/edition identifiers,
  multipart torrent submission and success/error responses. Remove live keys,
  cookies, passkeys, session identifiers and signed download URLs from examples.
- Music/soundtrack eligibility and transcode rules: accepted codecs/presets,
  sample rates, bit depth, dithering/resampling, channel layouts and provenance.
- Existing-release searches and what distinguishes an occupied format/edition
  from a genuinely missing one; any protected or non-trumpable releases.
- Torrent metainfo requirements and how to retrieve the exact accepted torrent
  or verify its infohash after upload; client-seeding expectations.

If AB only supports website submission, a browser/manual workflow must be
specified instead of inventing an upload API.

## Integration safety requirements

- Preserve original files, original tags and existing seeding registrations.
  Write each explicitly requested variant into a separate output directory.
- Reject lossy-to-lossy conversions and unsupported/unknown input layouts. A
  FLAC header alone is not proof of genuine lossless provenance.
- Require explicit approval for resampling, bit-depth changes and channel
  conversion according to the supplied rules, rather than guessing site policy.
- Retain exact source/profile/output checkpoints; validate output audio and tags
  before torrent creation. Never overwrite a different existing release.
- Separate planning, encoding, missing-format checks, submission and client
  registration. Recheck live eligibility before a NEW submission.
- Reuse durable upload intent/ACK recovery. An ambiguous submission needs
  on-site review, never an automatic POST replay.
- Use generated audio and fake tracker responses for tests; no real tracker
  uploads, account-wide crawling or source recategorization during development.

This document records an integration boundary, **not completed AB functionality**.
