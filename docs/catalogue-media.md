# Standalone Kitsune media-release tool

`tools/media-release.py` is a standalone entry point for **existing downloads**.
It needs no catalogue settings, CardinalDL account, tracker access, database, or
running dashboard. `tools/catalogue-media.py` remains a compatible alias. The
implementation uses Python's standard library plus `mkvmerge`, `mkvextract`,
`mkvpropedit`, `ffmpeg`, and `mediainfo` installed on the processing host.

## Web UI: existing-file Media tools

The private dashboard includes **Media tools**: download the standalone archive,
browse administrator-authorized **server folders**, auto-match a movie through
TMDB and IMDb, review the identity and derived filename, then explicitly type
`PROCESS COPY` to remux a new verified file. Ambiguous title/year matches are
never processed automatically. Exact public IDs may be supplied or recognized
in filenames; conflicting IDs fail closed.

Only normalized movie-title/year hints or public IDs are sent to TMDB, never
server paths. API throttles and the existing private UA TMDB key are reused; keys
are not exported to the browser or standalone archive. This screen currently
supports movies, not TV episode naming. Provider, audio-track choice, subtitle
corrections and read-only hardlink consent are reviewed in the preview.

Server folder access is explicitly configured by the administrator in the private
runner JSON, for example `"media_roots": ["/owned/downloads", "/owned/other-media"]`.
These roots are not editable through ordinary browser settings. Folders must be
canonical, owned, and not writable by other users; symlinks and path traversal
are rejected. Files on another computer are **not** accessible via a browser's
local path: download the `.pyz` and run it on that machine instead.

The output directory can be elsewhere under another authorized root. A missing
final subfolder is created only after explicit Process confirmation. Existing
output files are never overwritten. One media job runs at a time; it shares the
catalogue worker lock, supports cancellation of only its own process group, and
keeps originals. Preview does not transform media. The archive download requires
login and a verified hash receipt. No movie payload is uploaded through the UI.

## Portable single-file package

The standalone tool supports **Python 3.11+** and has no Python package
requirements. Build a self-contained archive (no config/account files included):

```sh
python tools/build-media-release.py --output /owned/path/media-release.pyz
python /owned/path/media-release.pyz --help
```

Copy that `.pyz` to another machine with the external media tools installed; the
Upload Assistant repository and catalogue service are not required there.

## Naming

```text
Title.Year.Resolution.Provider.WEB-DL.Audio[.Atmos][.DV][.HDR10Plus].Codec-Kitsune.mkv
```

Examples:

```text
Primetime.2026.1080p.AMZN.WEB-DL.DDP5.1.H.264-Kitsune.mkv
Your.Mother.Your.Mother.Your.Mother.2026.2160p.AMZN.WEB-DL.DDP5.1.Atmos.DV.H.265-Kitsune.mkv
Your.Mother.Your.Mother.Your.Mother.2026.2160p.AMZN.WEB-DL.DDP5.1.Atmos.DV.HDR10Plus.H.265-Kitsune.mkv
Your.Mother.Your.Mother.Your.Mother.2026.720p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-Kitsune.mkv
```

Supply the canonical title, release year, provider and exact IMDb/TMDB IDs.
Resolution, video/audio codecs, channels, Atmos and HDR labels come from the
actual MediaInfo data—not the old filename. Cropped 1920-wide movies still map
to 1080p. Missing multichannel layouts, ambiguous default audio tracks or
unsupported metadata fail closed rather than inventing a release label. Use
`--audio-index` to select a zero-based MediaInfo audio track when necessary.

IDs always go into Matroska `IMDB`/`TMDB` tags. The examples omit filename IDs;
`--filename-ids` optionally adds `.tmdb-123.imdb-tt1234567` before `-Kitsune`.

## Existing-file example

Create a separate owned output directory, then inspect a plan:

```sh
mkdir -p /downloads/processed
python tools/media-release.py /downloads/existing/movie.mkv \
  --output-dir /downloads/processed \
  --title 'Primetime' --year 2026 --provider AMZN \
  --imdb tt1234567 --tmdb 123
```

Add **`--execute`** only after reviewing the plan. A new output file is created;
the existing file is not renamed, rewritten or deleted. Existing destinations
are never overwritten. `--output /explicit/new.mkv` is also supported when no
standardized name is wanted. Input/output scopes must be owned directories with
no symlink components or writable-by-others directories. Separate owned output
folders are supported; this is not restricted to catalogue-created files.

Hardlinked inputs are refused by default. `--allow-linked-input` explicitly
allows read-only remuxing into a separate new file, preserving the original
inode, links and bytes. It does **not** authorize in-place edits of seeded files.
Subtitle aliases such as `eng`/`tam` normalize to `en`/`ta`; explicit corrections
use `--subtitle-language TRACK_ID=CODE`. Forced/default/SDH flags are preserved.
Unknown language is never guessed as English.

The dedicated server's private MKVToolNix directory is detected automatically:
`~/apps/ua-catalogue/media-tools/current/bin`. Other hosts can use system tools or
`--tool-bin /trusted/bin`. No system package replacement is required.

## Integrated remux/privacy cleanup

The same command performs the real mkvmerge remux, not a filename-only rename:

- Discards original global and track tags; retains only supplied public IMDb and
  TMDB identity tags. No source comments, encoder usernames, paths, account IDs,
  source URLs, custom device tags or old CardinalDL branding are copied.
- Clears the original container title and replaces track names with standardized
  language/role labels. Real mkvmerge writing/muxing application information is
  retained truthfully—not forged to impersonate a different tool.
- Removes encoded dates/statistics timestamps; regenerates segment/track UIDs;
  refuses remaining old linkage/UIDs. On older MKVToolNix versions, the real
  `mkvpropedit` edits track IDs only in the new private temporary output, never
  the original. Output filesystem mtime is normalized.
- Removes attachments, including potentially identifying cover art or font
  files. **Removing attached fonts may change ASS subtitle rendering**; the
  original remains available. Chapter times are retained with generic labels
  and new IDs; linked/ordered chapters require manual review.
- Verifies tags, headers, identities, subtitle codes/flags and HDR-related stream
  properties. SHA-256 copy-stream hashes must match for every audio/video stream.
  There is no audio/video transcoding, quality fallback or HDR conversion.

Warnings, missing tools or verification failures stop publication. Originals
remain untouched. Raw tool stderr and original private tags are not published.

### Privacy limits—important

This sanitizes **container metadata**, not all possible identifying information.
Lossless remuxing intentionally preserves audio/video packets: forensic/DRM
watermarks, in-band codec identifiers, visible text, voices or other identifying
content may remain. No claim of complete anonymity is made. MediaInfo's local
`Complete name`, filesystem owner, birth/ctime and access context are properties
of where a user inspects the file, not necessarily embedded release metadata;
this tool cannot erase operating-system or external logs. Use a non-identifying
output path when sharing reports, and do not publish private source manifests.

## Catalogue video modes

The dashboard supports saved-profile, SDR, HDR10, HDR10+, Dolby Vision,
DV+HDR10, DV+HDR10+, and HLG modes. Explicit choices are per-invocation overrides
with fallback disabled; saved Cardinal profiles stay unchanged. This standalone
module neither downloads content nor bypasses tracker, identity or entitlement
checks. Automatic post-download hookup is separate from processing existing
files; use this CLI explicitly until that hookup is implemented and verified.
