# LST recommendations — operator guidelines, 2026-10-19

The supplied rules supersede the previous LST snapshot. Recommendations cannot
prove visual quality, retail provenance, ownership, grades, splices, complete
retail packaging or staff decisions from a filename. REQUIRED evidence reviews
skip unattended uploads and default to No in attended mode. Known prohibited/
MUST violations are distinguished from ordinary occupied slots and cannot be
approved simply with a duplicate override. No reports are submitted in tests.

## Internal protection takes precedence

A non-internal or another internal group cannot replace an internal release,
even when it is dead or marked Trumpable. Only a verified same internal group
can replace it within the same known slot. Candidate internal eligibility uses
LST's enabled internal setting plus the matching configured group; a filename
claim alone does not confer eligibility.

An equivalent internal/back-catalogue release may coexist with an external;
a directly superior external may coexist with an internal, but the internal
remains. Different internal groups have no fixed global cap but must satisfy
ordinary meaningful coexistence/quality rules. Internal status alone never
proves quality. Back-catalogue equivalence is not a trump; a confirmed fix of
the issue that justified a low-quality Trumpable entry needs evidence.

Protected IDs are carried separately from displayed comparisons. UA excludes
them from report choices and rejects report POSTs against them. Bandwidth
refreshes inspect policy-bearing changes, revoke newly protected report intent,
and stop new evidence-required submissions. This uses observed site metadata;
it is not a promise of omniscient real-time server state.

## Slots, coexistence and replacement

- WEB-DL is per provider. SD has one per provider; 720p is H.264. 1080p and
  2160p provide H.264/H.265/AV1 positions; 1440p provides H.264/H.265. DV and
  HDR/DV-HDR H.265 are separate from SDR; HDR10+ and 3D are separate dimensions
  under the general rule. Different providers do not become trump targets.
- A WEB-DL retains its slot even when a WEBRip exists. A WEBRip needs clear
  visual-improvement comparisons to earn an additional same-provider/resolution/
  HDR position; neither format automatically trumps the other.
- The extra 2160p lossless WEB position is one global extra, not an extra for
  each provider. An ordinary provider's slot may itself contain lossless audio;
  its presence does not prove the global extra is occupied. Best/most-complete
  selection needs review rather than a bitrate/size inference.
- 720p/lower encodes require x264. 1080p separates SDR H.264/H.265/AV1 and HDR
  H.265/AV1; 2160p separates H.265/AV1 and their dynamic-range classes. Reasonably
  distinct size/quality/audio/master alternatives need evidence; LST has no
  invented universal 20% size cutoff. Near-identical same-master copies should
  not coexist. Different codec slots are not replacements for one another.
- Remuxes may coexist for distinct masters; source improvements, unique retail
  assets, original mixes/remixes, English dub, retail chapter names, chapters,
  required English PGS/forced subs and confirmed defects can justify trumps.
  Source/quality/asset improvement is not inferred from a larger file.
- WEB-layer hybrid DV/HDR10+ remuxes require demonstrated WEB-layer provenance
  for their dedicated slot. A HYBRID word alone is insufficient. Grade checks,
  HDR10+ plots and proof of correct/matching splices/layers are mandatory.
  Native-disc DV normally replaces WEB DV hybrid unless the hybrid is proven
  superior; internal protection still wins. Hybrid DV/HDR10+ supersedes hybrid
  DV/HDR only within the appropriate slot and with valid evidence.
- Actual alternate-cut differences must be documented; marketing/remaster labels
  are not cuts. Open Matte/OAR and 3D are separate. Extras/additional slots need
  justification, not automatic permissions.
- SD non-discs need absence of an equivalent HD retail source. DVD remux versus
  DVDRip requires checking the superior-video exception, not blind trumping.
  Season packs replace matching season/quality/source episodes subject to
  internal protection. Finished seasons do not accept new individual episodes.
- Dead/no-seeder targets require an equivalent/better replacement and remain
  subject to internal protection. Confirmed same-release REPACK/PROPER is not
  a cross-group internal override.

## Upload requirements and exceptions

Prohibited: declared pre-retail/bootleg sources (officially retail-released
workprints need proof), known bootleg distributors, malware/illegal/banned-group
content, archives, unlicensed/free public WEB, invalid splices/layer mismatches,
uploader AI video/audio/subtitle/HDR modifications, and extraneous files outside
MKV. Studio/distributor AI shipped untouched on retail is an exception requiring
provenance, not permission for uploader AI. Geolocation/library-card walls can
qualify for the stated WEB exception; YouTube alone is not eligibility proof.
Pornography cannot use Movies/TV; erotica/softcore needs valid IMDb.

Non-disc video MUST be MKV. TS broadcast exceptions, confirmed DV Profile 5 MP4
WEB-DL and sole-known-source XviD/DivX preservation exceptions need their actual
conditions verified. Non-MKV Movie/TV must explicitly use moderation queue even
with account bypass, and include the exception note. Bare DV does not prove
Profile 5; an empty search does not prove no other version exists.

All formats including discs require at least **three lossless screenshots** in
the actual description. Registered captures, requested count and known lossy
raw links are checked where available; unknown/externally reused evidence needs
confirmation. Required MediaInfo/BDInfo must actually be supplied.

### Audio and subtitles

Known required audio violations are flagged for correction before a new upload:

- Global LPCM: 3.0+ to DTS-HD MA or TrueHD plus compatibility; 2.0 to FLAC;
  1.0 to FLAC/DTS-HD MA. Anime FLAC 5.1 exception applies subject to format rules.
- HD 720p/1080p encodes override those conversion targets: multichannel main
  audio must be lossy except anime **16-bit FLAC 5.1**. Allowed mono/stereo
  lossless is 16-bit FLAC; higher bit depth requires dithering. Commentary and
  isolated score must be lossy, including anime. x264 is mandatory at 720p/lower.
- Other global multichannel FLAC is prohibited except qualifying anime 5.1.
  Every TrueHD needs DD core or allowed WEB DD/DD+/Atmos substitute. DEE <=5.2.1
  cannot create an industry-standard DD compatibility track. WEB compatibility
  is allowed; a proven better disc AC-3 may trump it, not an Atmos label alone.
- Outside anime, exactly one primary audio defaults Yes. Original language
  should be first/default. Original mixes, unique remixes/upmixes, English dub,
  commentary/interviews/novelty (not an AD loophole) and isolated score require
  the stated allowed-track purposes; redundant dubs/tracks are not justified.
- DTS-HD MA/TrueHD stereo SHOULD become FLAC; UHD audio may be lossless or lossy
  within global rules. Languages/titles and descriptive clarification matter.
- Non-English originals without English dub require English subtitles. External
  site subtitles are partial satisfaction; embedded English may trump them.
  Missing English entirely when another compliant upload exists is rejection.
  Default/forced flags, original/English forced scope, language tags and ordering
  follow the SHOULD guidance; on-site notes MUST clarify missing original-group
  tags. Personal Releases turn SHOULD into MUST.

The engine checks observable codec/channels/bit-depth/default flags and declared
violations, but cannot prove dithering, sync, translation quality, source mixes
or completeness from those fields. Remaining evidence must be verified.

### Full discs and moderation outcomes

Retail complete BDMV/HDDVD_TS/VIDEO_TS and 3D-Blu-ray ISO must retain menus/extras,
remove copy/region restrictions and include QUICK SUMMARY BDInfo or online
IFO MediaInfo plus VOB description spoiler. DVD5/9, BD25/50/66/100, HD-DVD/LD-ROM
have unlimited documented different-content/region slots. Do not split physical
discs. Retail box sets may stay together; duplicate main-feature UHD+HD discs
must split into one torrent per physical disc, with same-disc/extras exceptions.
Custom disc is allowed only before its unmodified equivalent, must be Trumpable,
and can be replaced by that equivalent; defects/packaging/reissues need proof.
Other formats never trump full discs.

Prohibited content, wrong mandatory container, missing required reports/settings,
wrong encoder/mode, wholly uncropped bars and unsupported downscaled-source claims
are rejection/removal issues, not convenient Trumpable labels. Audio-tier MUST
violations are rejected in queue; already-bypassed uploads are marked Trumpable.
SHOULD becomes MUST for Personal Releases. Anime FLAC 5.1 does not waive the
16-bit/dithering obligations. Source/quality/sync/cropping/subtitle/track-layout
Trumpable criteria still require actual evidence and internal protection.
UA does not automatically tag, nuke or certify existing torrents.
