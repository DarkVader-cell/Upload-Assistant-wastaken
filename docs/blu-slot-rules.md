# Blutopia (BLUTOPIA) slot and upload recommendations

Source: the operator-supplied BLU guidelines, recorded 2026-10-20. These are BLU rules, not LST/Aither/HDB policy. Staff are final arbiters; exceptions need the helpdesk. This integration is a recommendation and evidence gate, **not a claim that every upload requirement has been machine verified**. No live torrent or report is submitted by its tests.

## Decisions and scope

- Search the whole title (including other formats/resolutions); retain the ordinary filtered list for basic duplicate checks. A failed evaluation requires review, never a presumed vacant slot.
- Observable prohibited/MUST violations block and cannot be overridden with a basic duplicate override. Missing source, comparison, approval, report, language or format evidence requires review: unattended skips; attended asks **default No**, even in a vacant slot. No false cross-seed success is recorded.
- Ordinary native WEB vacancies can still be allowed when no missing-evidence condition exists. Operational commitments and general hygiene are advisory reminders, not invented claims about the uploader.
- BLU automatic trump reports are **not** introduced. A potential conflict is not proof of a valid report target. Case-by-case stream/asset comparisons remain necessary.

## Coexistence and trumping

All comparisons are scoped to the same title, relevant cut and resolution. No inferred universal extra slot per HDR metadata label.

| Format | Policy |
| --- | --- |
| Discs | All **unique**, unmodified retail discs coexist. Official retail disc box sets coexist with their individual discs. Uniqueness/contents need verification, not size/name guesses. |
| Remux | Normally one Blu-ray remux per cut/resolution. Different masters with meaningful colouring/framing differences coexist; same-master replacement requires demonstrably better video/audio or improved assets. Missing/defective tracks, forced subtitles or episodes can justify replacement. |
| WEB-DL | Provider differences coexist for the highest offering at each resolution/video-codec/colour-space combination. Same-provider HDR10/HDR10+/DV metadata alone does not establish separate slots or priority. Unknown traits require review. |
| HDTV | Normally one per cut/resolution. WEB season packs replace HDTV seasons/episodes unless proven inferior. |
| Encodes, including WEBRip | Meaningful benefits in quality, size or features; ordinary caps are **one 720p, two 1080p, one 2160p**, not multiplied per codec/provider/HDR label. Extra coexistence/exception needs a coherent staff-acceptable case. |
| WEBRip versus source WEB-DL | WEBRip needs comparison screens proving significant visual improvement to coexist with its source, including when source/output resolutions differ. WEB-DL normally trumps WEBRip of the same source/source resolution. A metadata layer is not visual/raw-stream superiority. |

REPACK/PROPER/RERip/RE-ISSUE replaces its actual original, not unrelated groups/releases. Complete same-season/same-quality/same-source packs replace episodes/incomplete packs. Individual seasons of the same source/resolution replace COMPLETE series packs. A superior WEB source can beat an inferior Blu-ray source; the label alone proves nothing. Wrong original filenames, missing original/English subtitles, and dying noncompliant uploads require an actual case.

Dead-equivalent cases require either (a) unanswered reseed request at least one week old **and** last seed activity over one month ago, or (b) last seed activity over two months ago with equal/better quality. Zero seeders alone proves neither.

SHOULD failures are trumpable; SHOULD is MUST for personal releases. Recommended improvements trump only while retaining **all** other existing qualities, including named chapters. MAY features alone create no automatic entitlement.

## HDR and hybrids

- Correctly created hybrids need matching masters, colour/brightness, aspect ratio throughout, and identical intros/outros. Invalid hybrids are prohibited.
- An original untouched HDR stream coexists with its derived hybrid and is encouraged alongside it. Never report it merely for lacking metadata.
- Same-VOD WEB-DL priority depends on real HDR/raw-stream quality, not added metadata: HDR10-only may beat P8.1. WEB-DL may beat WEBRip regardless of either release's metadata.
- UHD remuxes SHOULD use disc HDR10+/DV. Replacement must otherwise meet the same standards.
- Disc P7 MEL/FEL may replace P8.1 **subject to the exception** that Blu-ray-sourced P8.1 cannot be trumped by P7 MEL. P7 FEL beats P7 MEL only with equal/better HDR10 base quality. No numeric DV-profile rank is automatically applied.
- `hdr10plus_tool` and `truehdd` are prohibited. Second-source HDR10+ injection with `hdr10plus_tool` is prohibited; official-tool HDR10+ injection is allowed. Tool installation or a word in a filename is not evidence that it was used to create the payload.
- `dovi_tool` is discouraged but conditionally allowed. `deew` is discouraged, not banned; official Dolby encoding via `dee.exe`/XML is preferred.

### Derived WEB P5/P8 DV

Remuxes/encodes must use the **actual FANRES category route** (a TV edition string alone does not change the category). Above the unchanged original description, left aligned, include exactly:

```text
This release contains a Derived Dolby Vision layer. The WEB Dolby Vision layer was injected using dovi_tool. Mismatches between Blu-ray and WEB stream masters may occur.
```

Also require:
- HDR BD versus HDR WEB and HDR BD versus DV WEB converted to PQ grade comparisons;
- DV brightness plots for both sources;
- the DV source, Metafier log and `dovi_tool` summary.

Derived-DV WEB-DLs must **not** use HYBRID in their title. They require no derived alert/note; noting DV-layer source is SHOULD. The integration does not silently rewrite a description, fabricate logs or insert a FANRES category based on an unverified filename.

## Observable prohibitions and required evidence

Prohibited: extraneous payload files (NFOs, samples, screenshots, external subtitle files), sound recordings/music videos/software/literature/pornography/sportscasts, bootleg/pre-retail/social-platform content, PII/watermark steganography, banned groups and invalid hybrids. Existing tracker banned-group enforcement is retained; movie genres such as music/sport do not by themselves prove prohibited content. Foreign subtitles can be provided through the **subtitle manager**, not as extraneous torrent files.

Allowed categories include films/shorts/documentaries/stand-up, ProRes trailers, TV/mini/docu/anthology/daily shows, FanRes, special events and concerts. A declared ProRes-trailer exception requires source/codec/type/container review; it is not a generic way to bypass encode rules. Unmodelled content/format distinctions are not certified by an empty search.

- Single-file torrents have no enclosing directory. Multiple files use one top-level directory; further nesting only when the content permits. All files should have uniform resolution/source/format/group/name. Filenames require title, movie year or TV season/episode, and resolution; source/codec/origin are highly encouraged. Preserve recognised original group filenames; personal releases must use BLU conventions. An extra base folder is allowed for insufficiently descriptive names.
- Discs: BDMV/HDDVD_TS/VIDEO_TS, retail/unmodified, no custom/DIY. MVC 3D Blu-ray must be ISO. Copy/region protection SHOULD be removed; government warnings MAY be removed. Disc box sets alone permit multiple movies/seasons, and must be direct official retail rips.
- Encodes: 720p/1080p/2160p only, untouched sources, x264/x265 with metadata, CRF or multipass VBR, appropriate bitrate and reasonable cropping. **SDR live action uses x264.** Source/encode comparisons are required. Hi10P is anime-only; unknown animation status is not a live-action proof.
- SD DVD remux/WEB-DL: need no native non-upscaled HD release, never-HD OAR, or important unique assets/cuts/subtitles/commentary. No matching HD torrent on BLU does not prove this. Non-disc SD upscales require prior staff approval.
- Remux: retail untouched tracks, MKV. WEB-DL/untouched HDTV: untouched, fully decrypted tracks, MKV; confirmed DV P5 may use MP4; HDTV may use TS. Bare DV is not P5 proof.
- After a season fully airs, episodes have a **72-hour window from actual source release**, not airdate; afterward use a season pack. S01E01 pilots are exempt. Missing/naive source timestamps require review.
- Extras: separate from the movie/TV pack; streaming/disc source, source-faithful and descriptive. Use Behind The Scenes / Deleted Scenes / Featurettes / Interviews / Scenes / Shorts / Trailers / Other. SHOULD remain untouched unless encoding demonstrably improves quality.
- FanRes: distinguish the title and describe the project in detail; relevant movie/TV formatting rules still apply.
- WEB concerts require prior **forum staff approval** and **mod queue**. Concert MKVs require named tracklists. Include best lossless surround plus best lossless stereo/mono; mono DTS-HD MA 1.0, digital stereo may be FLAC 2.0. Lossless encode audio is preferred; 16-bit dither is acceptable, lossy is trumpable. Concert documentaries use regular documentary rules.

## Audio and subtitles

Non-discs: main audio in the title's primary language; English dub MAY accompany non-English primary audio. Every TrueHD needs a standalone AC-3 compatibility track, **bsid=6** (Advanced MediaInfo), no duplicate compatibility per mix and no separately extracted embedded cores. A WEB HLS compatibility track may accompany each non-HLS track, but does not erase the TrueHD AC-3 MUST. Verify mix correspondence; raw counts alone are insufficient.

Primary-source original mixes/commentaries/unique scores/music are SHOULD, all-source versions Recommended. Tags/names and subtitles SHOULD be accurate/in sync; don't convert native text subtitles to picture formats; force only native-language subtitles for non-native dialogue. Non-English content MUST have English subtitles, embedded or in the subtitle manager. SRT/ASS is preferred for encodes; difficult-to-OCR languages may use PGS.

Allowed video codecs generally: AVC/MVC, HEVC, AV1, VC-1, VP9, ProRes, Cineform, MPEG-2 and JPEG 2000. **The encode-specific x264/x265 rule still applies.** Unknown codec metadata does not prove it is prohibited or compliant.

Audio: DTS/DTS-HD/DTS:X, AC-3, E-AC-3, TrueHD; FLAC mono/stereo; AAC mono/stereo (multichannel only if untouched outside the stricter encode prohibition); MP2 only untouched HDTV/DVD; MP3 only qualifying supplementary material unavailable in original/suitable form. Opus/OGG/Vorbis and multichannel FLAC/AAC encodes are prohibited, except anime **FLAC 5.1** (not arbitrary multichannel layouts). BLU's anime exception is not LST's 16-bit-only rule.

Remux SHOULD preferences: mono DTS-HD MA 1.0 then FLAC 1.0; multichannel lossless DTS-HD MA/TrueHD; stereo FLAC 2.0.

### Encode audio tiers (evidence review, not inferred from filesize)

| Tier | Main audio |
| --- | --- |
| 2160p x265 | Lossless |
| 1080p x264/x265 Quality | TrueHD 5.1/7.1 **16-bit VBR** with 448/384 kbps AC-3 compatibility; FLAC 1.0/2.0; DD+ 7.1 1536/1664; DD+ 5.1 768/1024; DTS-HD HRA 7.1 2046 kbps |
| 1080p x264 Compromise | DD+ 7.1 1280; DD+ 5.1 768/1024; AAC 1.0/2.0 |

Additional detailed format guidance must be checked against the actual track purpose/source:
- Commentary only: HE-AAC 1/2ch 128; AAC-LC 1/2ch 160 kbps, official Fraunhofer FDK/Dolby encoders only.
- Mono primary/commentary DD/DD+ 1.0 192/224; stereo commentary/score/stereoized mono/LtRt DD/DD+ 2.0 192/224/256; LCR DD/DD+ 3.0 256/320 kbps. DD/DD+ mono preferred for secondary mono compatibility. Cinema stereo DD/DD+ 2.0 needs Dolby Surround flags.
- FLAC mono/LtRt 1/2ch 16-bit VBR preferred, current FLAC library; check superfluous dual mono.
- LCRS: DD 4.0 or preferred new-encode DD+ 4.0 384/448; direct-disc DTS 4.0 754.5 (768) kbps.
- Direct-source primary DD 5.1-EX 640; direct DTS-ES matrix 5.1/discrete 6.1 754.5/1509 (768/1536).
- New HQ DD+ 5.1/EX 768/1024; above that use dithered 16-bit TrueHD. DD+ 7.1 1280/1536/1664; DTS-HRA 7.1 2046. 1664/2046 only exceptionally demanding 24-bit soundtracks, not a blanket quality upgrade.
- TrueHD 5.1/EX 16-bit VBR with DD 384/448; 7.1 16-bit VBR with DD 5.1-EX 448, appropriate surround/downmix flags preferred. 24→16-bit dithering is allowed for efficient x264 multichannel lossless.
- Multichannel DTS-HD MA and 24-bit TrueHD are allowed-but-bloated, **not a blanket prohibited-codec rule**.
- Official Dolby/DTS encoders (Dolby Encoder Suite / DEE or DEEW; DTS-HD Encoder Suite v2.6.22) required; logs/provenance are not guessed from a codec name. Commentary SHOULD use DD+/DD/AAC mono/stereo.

Tier selection, exact allowed bitrate, encoder provenance, mix/compatibility correspondence, subtitle sync, transparency, non-bloat and asset retention remain evidence reviews. A playback-default dub or AC-3 compatibility track is not automatically the primary/native main track.

## Description and operational duties

English descriptions, no advertising/logos/recruitment/greetz/templates. At least **three valid screenshots**; Blu-ray ISO screenshots optional but encouraged. No invented JPEG/PNG restriction is added from another tracker.

Reports in the correct parser fields: DVD main-duration IFO plus largest VOB in a description spoiler; BD Quick Summary (full scan log in body if unavailable); HD-DVD first main EVO. Remux/WEB/encode MediaInfo, first episode for multifile TV. Source/eac3to logs encouraged for remuxes; source/comparisons/x264-x265 logs/filtering notes encouraged for encodes, with source/encode comparison itself required.

Seed at least seven days **OR** until five active seeders. New uploads must become snatchable promptly. If upload speed is below 100 Mbps or not connectable, SHOULD wait 24 hours **OR** two active seeders before another upload. The recommendation engine does not stop seeding, invent seed-history evidence, or change network/service configuration.

### Structured inputs and limits

Existing Meta/MediaInfo supply formats, tracks, languages, counts and names. Optional `BLUTOPIA_*` facts (e.g. tools used, derived DV, concert, source-release timestamp, actual planned file-layout faults) must represent observed/verified facts, not arbitrary filename guesses. No new UI switches or automatic source-history scraper are claimed. False/unknown facts never establish an exception. In particular, source timestamps require timezone, source authenticity and cutoff context; mod queue resolves upload flag plus tracker config. The docs above retain requirements that cannot safely be automated from available metadata.
