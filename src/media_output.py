"""Independent implementation of documented Unshackle video naming semantics.

Reference: docs.unshackle.dev/guide/output-and-naming/ (reference revision
b3d586a590325b30b146217d0db49cdc045944b2). No upstream implementation is bundled.
Technical labels come from MediaInfo; this module does not alter any streams.
"""

from __future__ import annotations

import re
import unicodedata
from fractions import Fraction

FIELDS = frozenset(
    [
        "title",
        "year",
        "season",
        "episode",
        "season_episode",
        "episode_name",
        "part",
        "absolute",
        "date",
        "quality",
        "resolution",
        "source",
        "tag",
        "audio",
        "audio_channels",
        "audio_full",
        "atmos",
        "dual",
        "multi",
        "dubbed",
        "video",
        "hdr",
        "hfr",
        "edition",
        "repack",
        "lang_tag",
        "title_type",
    ]
)
TOKEN = re.compile(r"\{\s*([a-z_]+)(\?)?\s*\}")


def _get(track, *names):
    values = {key.replace("_", "").lower(): value for key, value in track.items()}
    return next((values.get(name.replace("_", "").lower()) for name in names if values.get(name.replace("_", "").lower()) not in (None, "")), None)


def _language(value):
    if not value:
        return ""
    try:
        from langcodes import Language

        result = Language.get(str(value)).prefer_macrolanguage().language
        return "no" if result in {"nb", "nn"} else result or ""
    except ImportError:
        text = str(value).split("-")[0].lower()
        if re.fullmatch("[a-z]{2}", text):
            return "no" if text in {"nb", "nn"} else text
        raise ValueError("Language-aware naming requires the langcodes package") from None
    except (ValueError, LookupError):
        return ""


def resolution(width, height):
    sides = [float(value) for value in (width, height) if value is not None and float(value) > 0]
    if not sides:
        return None
    short, long = min(sides), max(sides)
    for standard in (2160, 1440, 1080):
        if abs(short - standard) <= 16:
            return standard
    target = max(short, long * 9 / 16)
    nearest = min((4320, 2160, 1440, 1080, 720, 576, 540, 480, 360, 240), key=lambda number: abs(number - target))
    return nearest if abs(nearest - target) <= nearest * 0.1 else round(target)


def sanitize(value, separator=".", unicode_filenames=False):
    text = unicodedata.normalize("NFC", str(value))
    if not unicode_filenames and not text.isascii():
        try:
            from unidecode import unidecode
        except ImportError:
            raise ValueError("ASCII filename transliteration requires Unidecode; enable Unicode filenames or install Unidecode") from None
        text = unidecode(text)
    if not unicode_filenames:
        text = re.sub(r"\[\(+", "[", text)
        text = re.sub(r"\)+\]", "]", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Cc").replace("/", " & ").replace(";", " & ")
    if separator == ".":
        text = text.replace(" - ", ".")
    text = re.sub(r"[:; ]", lambda _match: separator, text)
    text = re.sub(r"""[\\*!?¿,'"<>|$#~]""", "", text)
    text = re.sub(re.escape(separator) + r"{2,}", lambda _match: separator, text)
    return unicodedata.normalize("NFC", text.strip(" ."))


def format_name(template, context, unicode_filenames=False, separator_override=None):
    if not isinstance(template, str) or not 1 <= len(template) <= 500:
        raise ValueError("Invalid output template")
    remaining = TOKEN.sub("", template)
    if "{" in remaining or "}" in remaining:
        raise ValueError("Unsupported template expression")
    references = list(TOKEN.finditer(template))
    if any(match[1] not in FIELDS for match in references):
        raise ValueError("Unknown output-template variable")
    missing = [match[1] for match in references if not match[2] and match[1] not in context]
    if missing:
        raise ValueError("Missing required template variables: " + ", ".join(missing))
    between = "".join(re.findall(r"\}([^{}]*)\{", template))
    separator = separator_override or (" " if between.count(" ") > between.count(".") else ".")
    rendered = template
    for match in references:
        marker = match[0]
        value = context.get(match[1], "")
        if match[2] and not value:
            index = rendered.find(marker)
            if index < 0:
                continue
            start, end = index, index + len(marker)
            left = rendered[start - 1 : start] if start else ""
            right = rendered[end : end + 1]
            left_sep = bool(left) and left in ".- \t\n"
            right_sep = bool(right) and right in ".- \t\n"
            if left_sep and right_sep:
                if right == "-":
                    start -= 1
                else:
                    end += 1
            elif left_sep:
                start -= 1
            elif right_sep:
                end += 1
            rendered = rendered[:start] + rendered[end:]
        else:
            rendered = rendered.replace(marker, str(value if value is not None else "").strip())
    rendered = re.sub(r"\.{2,}", ".", rendered).replace(".-", "-")
    rendered = re.sub(r"[.\s]+([)\]])", r"\1", rendered)
    rendered = re.sub(r"\(\s*\)|\[\s*\]", "", rendered)
    rendered = re.sub(r"\s{2,}", " ", rendered)
    rendered = re.sub(r"(?:-\s*)+-", "-", rendered).strip(". -\t\r\n")
    return sanitize(rendered, separator, unicode_filenames) or "untitled"


def context(info, title, year, provider, group="", original_language=None, audio_index=None, options=None, title_data=None):
    options = options or {}
    data = title_data or {}
    tracks = info.get("media", {}).get("track", [])
    videos = [track for track in tracks if track.get("@type") == "Video"]
    audios = [track for track in tracks if track.get("@type") == "Audio"]
    if not videos or not audios:
        raise ValueError("Video naming requires video and audio tracks")
    original = _language(original_language)
    langs = [_language(_get(track, "Language")) for track in audios]
    if audio_index is not None:
        if type(audio_index) is not int or not 0 <= audio_index < len(audios):
            raise ValueError("Audio index is outside the file")
        audio = audios[audio_index]
    else:
        audio = next((track for track, lang in zip(audios, langs, strict=True) if original and lang == original), audios[0])
    video = videos[0]
    codec_names = options.get("codec_names", {})

    def rename(value):
        output = codec_names.get(value, value)
        return "" if output is None else str(output)

    width, height = _get(video, "Width"), _get(video, "Height")
    tier = resolution(width, height)
    video_format = str(_get(video, "Format") or "")
    video_codec = rename({"AVC": "H.264", "HEVC": "H.265"}.get(video_format, video_format))
    audio_format = str(_get(audio, "Format") or "")
    builtin = {"E-AC-3": "DDP", "DD+": "DDP", "AC-3": "DD", "DTS-UHD": "DTS-X", "DTS LBR": "DTS-LBR", "MPEG-H 3D Audio": "MPEG-H"}.get(audio_format, audio_format)
    audio_codec = rename(builtin)
    layout = str(_get(audio, "ChannelLayout", "ChannelLayout_Original") or "").split()
    lfe = sum(part.upper().startswith("LFE") for part in layout)
    heights = sum(part.upper().startswith("T") for part in layout)
    if heights:
        channels = f"{len(layout) - heights - lfe}.{lfe}.{heights}"
    elif layout:
        channels = f"{sum(0.1 if part.upper().startswith('LFE') else 1 for part in layout):.1f}"
    else:
        channels = f"{float(_get(audio, 'Channels', 'Channel_s') or 0):.1f}"
    atmos = any("JOC" in str(_get(track, "Format_AdditionalFeatures") or "") or str(_get(track, "JOC") or "").lower() not in {"", "0", "no", "false"} for track in audios)
    hdr_format = str(_get(video, "HDR_Format") or "")
    commercial = str(_get(video, "HDR_Format_Commercial", "HDR_Format_Commercial_IfAny") or "")
    transfer = str(_get(video, "TransferCharacteristics", "transfer_characteristics", "transfer_characteristics_Original") or "")
    ranges = {"HDR10": "HDR", "HDR10+": "HDR10P", "Dolby Vision": "DV", "HDR10 / HDR10+": "HDR10P", "HDR10 / HDR10": "HDR"}
    hdr = ""
    base = ranges.get(commercial)
    if commercial:
        if hdr_format.startswith("Dolby Vision"):
            profile = str(_get(video, "HDR_Format_Profile") or "")
            if base in {None, "DV"} and "PQ" in transfer and profile.startswith(("dvhe.07", "dvhe.08")):
                base = "HDR"
            hdr = "DV" + ("." + base if base and base != "DV" else "")
        elif hdr_format.startswith("HDR Vivid"):
            hdr = "HDR"
        else:
            hdr = base or ""
    elif "HLG" in transfer:
        hdr = "HLG"
    elif "PQ" in transfer:
        hdr = "HDR"
    # Native JSON may expose compatibility rather than the commercial alias.
    if not commercial and hdr_format:
        if "Dolby Vision" in hdr_format:
            hdr = "DV" + (".HDR10P" if "2094" in hdr_format or "HDR10+" in hdr_format else "")
        elif "HDR10+" in hdr_format or "2094" in hdr_format:
            hdr = "HDR10P"
        elif "HDR10" in hdr_format:
            hdr = "HDR"
    hdr = ".".join(filter(None, (rename(part) for part in hdr.split("."))))
    try:
        rate = float(Fraction(str(_get(video, "FrameRate") or "0")))
    except (ValueError, ZeroDivisionError):
        rate = 0
    distinct = set(langs) - {""}
    strict = options.get("dual_multi_mode", "strict") != "count"
    values = dict.fromkeys(FIELDS, "")
    values.update(
        title=str(title).replace("$", "S"),
        year=year or "",
        source="" if options.get("no_source") else provider,
        tag=group,
        quality=f"{tier}{'i' if str(_get(video, 'ScanType') or '').lower() == 'interlaced' else 'p'}" if tier else "",
        resolution=str(tier) if tier else "",
        video=video_codec,
        audio=audio_codec,
        audio_channels=channels,
        audio_full=audio_codec + (" " if builtin == "DTS-X" or audio_codec[-1:].isdigit() else "") + channels,
        atmos="Atmos" if atmos else "",
        hdr=hdr,
        hfr="HFR" if rate > 30 else "",
        dual="DUAL" if len(distinct) == 2 and (not strict or (original and original in distinct)) else "",
        multi="MULTi" if len(distinct) > 2 else "",
        dubbed="DUBBED" if strict and len(distinct) == 1 and original and original not in distinct else "",
        title_type=data.get("title_type", "movie"),
        edition=data.get("edition", ""),
        repack="REPACK" if data.get("repack") else "",
        lang_tag=data.get("lang_tag", ""),
    )
    if data.get("title_type") in {"series", "sports"}:
        season, episode = data.get("season"), data.get("episode")
        if type(season) is not int or season < 0 or type(episode) is not int or episode < 1:
            raise ValueError("Series naming requires exact season and episode numbers")
        values.update(
            season=f"S{season:02d}",
            episode=f"E{episode:02d}",
            season_episode=f"S{season:02d}E{episode:02d}",
            episode_name=data.get("episode_name", ""),
            absolute=f"{data['absolute']:03d}" if type(data.get("absolute")) is int else "",
            part=data.get("part") or "",
        )
        if data.get("date"):
            from datetime import date

            day = date.fromisoformat(data["date"])
            display = day.isoformat().replace("-", ".")
            values.update(season=display, episode="", season_episode=display, year="", date=display if data["title_type"] == "sports" else day.isoformat())
        if data.get("part"):
            suffix = f".Part.{int(data['part'])}"
            values["episode"] += suffix
            values["season_episode"] += suffix
    for rule in options.get("tag_rules", []):
        if all(str(values.get(key, "")).casefold() in [str(item).casefold() for item in (val if isinstance(val, list) else [val])] for key, val in rule["when"].items()):
            values["tag"] = rule["tag"]
            break
    return values
