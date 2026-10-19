# HDBits recommendations — operator rules, 2026-10-19

This implements **HDBits**, not HD-Torrents. The supplied rules do not define a
universal numbered SDR/HDR/provider slot matrix: UA does not invent those slots.
It checks known prohibitions and asks for evidence for conditional coexistence,
replacement, reservation and source requirements. Unknown inventory is not a
vacant slot. `DEFAULT.slot_rules = False` is an explicit engine override.

## Rights and comparisons

Encodes/remuxes require verification of open lotteries, offers and source
in-progress claims. Upcoming member encodes/remuxes take precedence. The stated
remux rights expire 48 hours after the relevant button/lottery event, not after
a timestamp UA invents. Better sources can have a fresh lottery. TV signup
rights, 48-hour deadlines, permission, comments and missed-deadline history
require actual site verification.

- A scene/external encode replacement needs proven improvement and **4–6
  source/new/old B-frame comparisons**, except the stated dead-release exception.
- Internal encode/WEB coexistence needs **4–6 source/new/WEB B-frame comparisons**
  whichever arrives later. Exceptions: dead releases, 720p WEB-DL, and **Movies
  Anywhere 4K WEB-DL**, which can be uploaded without those comparisons.
- An internal encode replacement needs **5–10 source/new/old B-frame comparisons**
  and confirmed fixes, a noticeably better source or significant audio/video
  improvement plus transparency. Subtitles, commentary and marginal changes
  alone do not suffice. Filesize alone is not quality proof.
- Compare Blu-ray against an existing high-bitrate 4K SDR WEB before encoding;
  only the best source/version is eligible, and lottery rights still apply.
- Document regional full-disc audio/subtitle differences; a new region label
  does not automatically establish different contents. FLAC alone is not a
  remux trump reason. Zero seeders is not silently treated as verified death.

## Format, audio and source verification

Known prohibited cases include banned encode groups, 720p HDR encodes/WEB,
non-3D disc ISOs, BD5/BD9, declared custom discs/re-encodes/public downloads,
archives, screeners/cam/R5 sources, descriptive audio and declared non-animation
dubs. Required foreign-speech forced subtitles must be muxed/default. Modified
payloads need changed filenames. Native source and audio declarations are not
inferred from a name. Upscale exceptions for high-quality anime or multichannel
lossless concerts need review. 3D discs must be ISO; 3D video must be SBS or
frame sequential. HD PVR needs correct framerate/no interlacing and Encode
category. WMV HD/D-Theater/DVD-A, IPTV/WEB-CAP, offers, MKA tracks and 4.0+
professional multichannel music need their specific eligibility checked.

HD HEVC/10-bit AVC at 720p/1080p needs exhaustive comparison proof of better
quality or **at least 20% bitrate reduction at the same picture quality**.
A 20% filesize difference does not establish that exception.

Remux/UHD audio and logs require manual validation:

- MKV, untouched best video/native primary audio; original mono/stereo defaults
  when an upmix also exists; available forced original-language PGS, non-SDH
  English PGS and chapters.
- eac3to >=3.52 with `-normal` CRC checks (the stated 3.34 exception only for
  discs without seamless branching/Atmos); DGDemux/MakeMKV alternatives still
  need the chosen playlist's eac3to `-check -normal` log. Use latest tools.
- Lossless mono/stereo can remain untouched or be FLAC via eac3to with logs.
  Multichannel LPCM requires official DTS-HD MA conversion; preserve TrueHD
  (optional embedded AC-3 for compatibility) and other codecs untouched.
- 720p multichannel: preferably AC-3 640 kbps; DD+ from lossless when applicable
  needs 160–192 kbps/channel. Stereo/mono AAC or FLAC from lossless; AAC preferred.
- 1080p multichannel: DD+/AC-3/DTS, DD+ 160–192 kbps/channel; stereo/mono AAC/FLAC;
  source DTS-HD HR allowed. Concerts can retain original lossless audio.
- External 720p/1080p encodes may retain original lossy/lossless audio; internals
  must not create DTS 768 kbps or mono/stereo DTS from lossless. UHD follows
  remux audio rules. English dubs are allowed only for animation. Commentary,
  original subs and eligible retail/OCR SRT need their stated source rules.

## Packaging and description

Completed/all-at-once WEB-DL/external WEBRip seasons must be packed, never
multiple seasons. Single episodes must be folderless torrents (a directory
selected as input is not proof of torrent layout). Weekly final episode precedes
the pack; preserve episode filenames, no subfolders/samples/NFOs, and do not
remove individual episodes yourself. Porn requires at least one month per pack.

Use IMDb-based readable titles with edition/resolution/source/country/codecs,
not scene separators or prohibited promotional tags. Descriptions need English,
MediaInfo/complete disc contents and BDInfo main-playlist bitrate scans; remuxes
need source/demux/conversion logs. TV/documentary IDs/poster fallbacks, movie
synopsis fallback, music set/track lists, sports spoiler warnings and XXX cast
information remain category-specific requirements, not automatically verified
by the slot engine.

Screenshots: at least **2 full-size untouched PNGs**; multi-file collections/packs
need 2 per encoding/source and at least 4 total. HDB thumbnails are recommended.
The operator's previous **warn-and-continue screenshot policy remains intact**:
this engine does not abort solely because image rehosting failed. Check the site
and repair missing screenshots manually.

Required evidence REVIEW decisions do not silently pass unattended, even for an
otherwise vacant slot; attended confirmation defaults to No. No approval,
reservation expiry, transparency, source authenticity or log validity is
fabricated. Tests use synthetic metadata, not live tracker submissions.
