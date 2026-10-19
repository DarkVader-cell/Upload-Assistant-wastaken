"""Observable LST prohibitions and evidence requirements, not auto-moderation."""
import re
from pathlib import Path

from src.meta import Meta
from src.screenshot_manifest import files as manifest_files
from src.slot_rules.profile import DISC, DV, ENCODE, H264, HDR10, HDR10P, HDTV, WEBDL, XVID, audio_family, channel_count


def lst_requirements(upload, meta, existing):
    pending = []
    if upload.kind == ENCODE and upload.resolution in {'SD', '720p'} and upload.codec not in {H264, XVID}:
        return '720p and lower encodes MUST use x264; x265/AV1 are prohibited', pending
    if upload.codec == XVID and existing:
        return 'XviD/DivX preservation exception requires no other version in any format', pending
    if not isinstance(meta, Meta):
        return None, pending
    get = meta.get
    source = str(meta.source or '').upper()
    if source in {'CAM', 'TS', 'TC', 'TELESYNC', 'TELECINE', 'R5', 'DCP', 'THEATER', 'DDC', 'SCREENER', 'DVDSCR', 'BOOTLEG'}:
        return 'Pre-retail/theater/bootleg sources are prohibited', pending
    if source in {'WORKPRINT', 'WP'}:
        pending.append('Verify this is an officially retail-released workprint, not prohibited pre-retail content')
    if str(get('distributor') or '').casefold() in {'resen', 'llamentol', 'impulso'}:
        return 'The declared distributor is a known bootleg source', pending
    if any(get(k) is True for k in ['illegal_content', 'malware_release', 'LST_banned_group', 'LST_invalid_hybrid']):
        return 'Declared illegal/malware/banned-group content or invalid hybrid is prohibited', pending
    ai = any(get(k) is True for k in ['ai_generated', 'ai_enhanced', 'ai_upscaled', 'ai_dv_hdr_layers', 'ai_subtitles'])
    if ai and get('LST_studio_ai_retail') is not True:
        return 'Uploader-applied AI generation/enhancement of video, audio, subtitles or HDR layers is prohibited', pending
    if ai:
        pending.append('Verify AI processing shipped untouched on the studio/distributor retail source; this does not permit uploader AI modifications')
    if Path(meta.path or '').suffix.lower() in {'.rar', '.zip', '.7z'}:
        return 'Archived/RAR releases are prohibited', pending
    if get('publicly_available') is True:
        if get('geolocked') is True or get('library_card_required') is True:
            pending.append('Verify the geolocation/library-card wall exception and licensed retail assets')
        else:
            return 'Free/public WEB sources are prohibited without the stated access-wall exception', pending
    if str(meta.service or '').casefold() in {'yt', 'youtube'}:
        pending.append('Verify the YouTube/access-wall exception and licensed retail status; a provider name alone is not proof')
    if get('LST_missing_track_clarification') is True:
        pending.append('Missing audio/subtitle language/title tags must be explained in the on-site description')
    if get('unlicensed_source') is True:
        return 'Only retail/licensed assets may be used', pending
    if (get('softcore') is True or get('erotica') is True) and not meta.imdb_id:
        return 'Erotica/softcore in Movies/TV requires a valid IMDb ID', pending
    if get('pornographic') is True and meta.category in {'MOVIE', 'TV'}:
        return 'Pornography must not use Movies/TV; erotica/softcore needs a valid IMDb ID', pending
    if get('LST_extraneous_files'):
        return 'Extraneous NFO/sample/Plexmatch/loose-subtitle files outside MKV are prohibited', pending
    if meta.category == 'TV' and not meta.tv_pack:
        if get('season_completed') is True or get('season_released_all_at_once') is True:
            return 'Finished/all-at-once TV seasons require season packs, not individual episodes', pending
        if get('season_completed') is not False:
            pending.append('Verify the season is still airing; completed seasons require packs')
    if upload.kind == DISC:
        if any(get(k) is True for k in ['LST_copy_protected', 'LST_region_locked', 'LST_missing_disc_assets']):
            return 'New full-disc uploads must be complete with copy/region restrictions removed; existing defective discs may be Trumpable', pending
        custom = get('LST_custom_disc') is True or bool(re.search(r'\bcustom\b', meta.edition, re.I))
        iso = meta.container.lower() == 'iso' or Path(meta.path or '').suffix.lower() == '.iso'
        if iso and not upload.is_3d:
            return 'Disc ISO is allowed only for 3D Blu-ray', pending
        if custom and get('LST_unmodified_same_disc_exists') is True:
            return 'A custom disc is not allowed after the unmodified same disc is available', pending
        pending.append('Verify retail complete disc format, removed copy/region protection, QUICK SUMMARY BDInfo or online IFO/VOB reports, retail box-set packaging and at least three lossless screenshots')
        if custom:
            pending.append('Custom disc requires no unmodified same-disc upload and must be marked Trumpable; UA does not invent that tag')
        if get('LST_mixed_resolution_same_feature_discs') is True:
            return 'Separate physical UHD/HD discs of the same feature must be separate torrents; same-disc content/extras exceptions need verification', pending
        return None, pending
    container = meta.container.lower() or Path(meta.path or '').suffix.lower().lstrip('.')
    if container not in {'mkv', 'matroska'}:
        dv5 = upload.kind == WEBDL and re.search(r'dv(?:he|h1)\.0?5\b|(?:dv|dolby.?vision).*?profile[ .:_-]*5\b', str(meta.mediainfo) + ' ' + meta.edition, re.I)
        possible_dv5 = upload.kind == WEBDL and DV in (upload.hdr or ()) and not (upload.hdr or frozenset()) & {HDR10, HDR10P}
        legacy = upload.codec == XVID and container in {'avi', 'mkv'}
        transport = upload.kind == HDTV and container in {'ts', 'mpeg-ts'}
        if not container:
            pending.append('Verify MKV container or a permitted non-MKV exception')
        elif not ((dv5 or possible_dv5) and container in {'mp4', 'mpeg-4'}) and not legacy and not transport:
            return 'Non-disc video MUST be MKV outside TS, confirmed DV Profile 5 MP4, or sole-source XviD/DivX exceptions', pending
        else:
            if meta.category in {'MOVIE', 'TV'} and not get('LST_modq_effective', meta.modq):
                return 'Non-MKV Movie/TV exceptions MUST be submitted to moderation queue, even with bypass; enable modq and provide an exception note', pending
            if possible_dv5 and not dv5:
                pending.append('Confirm Dolby Vision Profile 5; a bare DV label does not establish the MP4 exception')
            pending.append('Non-MKV Movie/TV exception requires moderation queue even with bypass and an explanatory upload note')
    if upload.codec == XVID:
        if existing:
            return 'XviD/DivX preservation exception applies only when no other version exists in any format', pending
        pending.append('Verify sole-known-source XviD/DivX preservation exception; empty search is not proof')
    if not meta.mediainfo:
        pending.append('Provide required MediaInfo in the upload parser; an absent report is a rejection issue, not a trump reason')
    tracks = (meta.mediainfo or {}).get('media', {}).get('track', [])
    audios = [t for t in tracks if isinstance(t, dict) and t.get('@type') == 'Audio']
    genres = ' '.join(str(x) for x in (meta.genres or []))
    anime = get('anime') is True or 'anime' in genres.casefold()
    hd_encode = upload.kind == ENCODE and upload.resolution in {'720p', '1080p'}
    families = [audio_family(' '.join(str(t.get(k) or '') for k in ['Format','Format_Commercial_IfAny','Format_AdditionalFeatures'])) for t in audios]
    for track, family in zip(audios, families, strict=True):
        channels = channel_count(str(track.get('Channels') or ''))
        bits = str(track.get('BitDepth') or '')
        title = str(track.get('Title') or '')
        lossless = family in {'flac','truehd','dts-hd ma','lpcm'}
        if family == 'lpcm' and channels:
            return 'LPCM must be converted using the applicable global/encode channel targets', pending
        if channels and channels >= 3 and family == 'flac' and not (anime and channels == 6):
            return 'Multichannel FLAC is prohibited except qualifying anime FLAC 5.1', pending
        if hd_encode:
            if family == 'flac' and bits and bits != '16':
                return 'Required audio-tier violation: all HD-encode FLAC must be 16-bit with required dithering', pending
            if lossless and re.search(r'commentary|isolated.?score', title, re.I):
                return 'Required audio-tier violation: HD commentary/isolated score must be lossy, including anime', pending
            if channels and channels >= 3 and lossless and not (anime and channels == 6 and family == 'flac' and bits == '16'):
                return 'Required audio-tier violation: HD multichannel main audio must be lossy except anime 16-bit FLAC 5.1', pending
            if channels in {1, 2} and lossless and family != 'flac':
                return 'Required audio-tier violation: HD mono/stereo lossless must be 16-bit FLAC or use lossy audio', pending
    if 'truehd' in families and not any(f in {'dd','dd+'} for f in families):
        pending.append('Verify each TrueHD track has its DD core or allowed WEB DD/DD+/Atmos substitute')
    if (audios and not anime and all('Default' in t for t in audios)
            and sum(str(t['Default']).casefold() in {'yes','1','true'} for t in audios) != 1):
        return 'Exactly one primary audio track must be Default Yes outside anime conventions', pending
    if upload.kind == ENCODE:
        pending.append('Verify retail untouched source, x264/x265/AV1, CRF or 2-pass VBR, cropped black bars and encode settings in MediaInfo; source resolution must justify below-HD. Check HD lossy/16-bit FLAC rules, required dithering and lossy commentary/isolated score')
        if get('LST_uncropped_black_bars') is True or get('LST_invalid_encode_mode') is True:
            return 'Uncropped black bars or non-CRF/non-2-pass encoding requires rejection, not a Trumpable tag', pending
        if get('LST_missing_encode_settings') is True:
            return 'Encode settings must be included in MediaInfo', pending
    if upload.hybrid:
        pending.append('Verify retail hybrid assets and proof of proper video/audio splices where performed')
        if upload.hdr and upload.hdr & {DV, HDR10P}:
            pending.append('Hybrid DV/HDR10+ layers need matching HDR base, grade check and HDR10+ plot; native-disc priority for WEB layers has the proven-superior hybrid exception')
    if get('LST_dither_required') is True and get('LST_dithered') is False:
        return 'Required FLAC bit-depth reduction was not dithered', pending
    if get('LST_modified_release') is True:
        pending.append('A modified third-party release can be Trumpable by the unmodified version; verify original files/names/metadata')
    if meta.personalrelease:
        pending.append('Personal release: all SHOULD requirements are MUST, including applicable sources, comparisons, logs, notes and track hygiene')
    captured = manifest_files(meta.base_dir, meta.uuid, 'main') if meta.base_dir and meta.uuid else []
    lossy_links = any(isinstance(image, dict) and re.search(r'\.(?:jpe?g)(?:[?#]|$)', str(image.get('raw_url') or ''), re.I) for image in (meta.image_list or []))
    if len(captured) < 3 or int(meta.screens or 0) < 3 or lossy_links:
        pending.append('Verify at least three lossless screenshots are actually included in the description; a thumbnail/JPEG extension is not lossless proof')
    original = str(meta.original_language or '').casefold()
    english = {'en','eng','english'}
    if original and original not in english | {'und','unknown'}:
        dub = bool((upload.audio_languages or frozenset()) & english)
        subs = bool((upload.subtitle_languages or frozenset()) & english)
        if not dub and not subs:
            pending.append('Non-English original without English dub needs English subtitles; external-only is partial satisfaction and embedded English may trump it. Missing entirely with another English-subtitled upload is rejection, not an automatic trump')
    return None, pending
