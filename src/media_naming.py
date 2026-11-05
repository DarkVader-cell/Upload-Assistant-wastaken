"""Standalone release-name derivation from MediaInfo, never from the old name."""

from __future__ import annotations

import re
import unicodedata


class NamingError(ValueError):
    """Media data is insufficient/ambiguous for an honest release label."""


def title_token(title: str) -> str:
    if not isinstance(title, str) or len(title) > 300:
        raise NamingError("A canonical title of at most 300 characters is required")
    text = unicodedata.normalize("NFKC", title).strip()
    text = re.sub(r"['\u2019\u2018]", "", text)
    text = re.sub(r"[^\w-]+", ".", text, flags=re.UNICODE).strip(".-_")
    if not text or text in {".", ".."}:
        raise NamingError("Canonical title has no safe filename characters")
    return text


def _number(value):
    text = str(value or "").strip()
    if not re.fullmatch(r"[0-9]+", text):
        raise NamingError("MediaInfo numeric value is missing or ambiguous")
    return int(text)


def release_name(info: dict, title: str, year: int, provider: str, group="Kitsune", audio_index=None) -> str:
    """Title.Year.Res.Provider.WEB-DL.Audio[.Atmos][.DV][.HDR10Plus].Codec-Group.mkv."""
    if type(year) is not int or not 1870 <= year <= 2100:
        raise NamingError("A valid canonical release year is required")
    if provider not in {"AMZN", "NF", "ATVP", "DSNP", "HMAX", "MAX", "HULU", "PMTP", "PCOK", "iT", "CR"}:
        raise NamingError("Provide an explicit recognized WEB provider")
    if not isinstance(group, str) or not re.fullmatch(r"[A-Za-z0-9]{1,32}", group):
        raise NamingError("Release group must be a short alphanumeric name")
    tracks = info.get("media", {}).get("track", [])
    videos = [track for track in tracks if track.get("@type") == "Video"]
    audios = [track for track in tracks if track.get("@type") == "Audio"]
    if len(videos) != 1 or not audios:
        raise NamingError("Exactly one video and at least one audio track are required")
    if audio_index is None:
        defaults = [track for track in audios if str(track.get("Default", "")).lower() in {"yes", "true", "1"}]
        if len(defaults) == 1:
            audio = defaults[0]
        elif len(audios) == 1:
            audio = audios[0]
        else:
            raise NamingError("Choose an audio index when multiple tracks have no unique default")
    elif type(audio_index) is int and 0 <= audio_index < len(audios):
        audio = audios[audio_index]
    else:
        raise NamingError("Audio index is outside the actual MediaInfo audio tracks")
    video = videos[0]
    width, height = _number(video.get("Width")), _number(video.get("Height"))
    effective = max(height, round(width * 9 / 16))
    tier = min([480, 540, 576, 720, 1080, 1440, 2160, 4320], key=lambda value: abs(value - effective))
    if abs(tier - effective) > max(16, tier * 0.08):
        raise NamingError("Video dimensions do not establish a standard resolution tier")
    codec = str(video.get("Format") or video.get("CodecID") or "").upper()
    if codec in {"AVC", "H264", "H.264", "V_MPEG4/ISO/AVC"}:
        codec = "H.264"
    elif codec in {"HEVC", "H265", "H.265", "V_MPEGH/ISO/HEVC"}:
        codec = "H.265"
    elif codec in {"AV1", "V_AV1"}:
        codec = "AV1"
    else:
        raise NamingError("Unsupported/unknown WEB video codec")
    audio_format = str(audio.get("Format") or audio.get("CodecID") or "").upper()
    if audio_format in {"E-AC-3", "EAC3", "A_EAC3"}:
        audio_format = "DDP"
    elif audio_format in {"AC-3", "AC3", "A_AC3"}:
        audio_format = "DD"
    elif audio_format in {"MLP FBA", "TRUEHD", "A_TRUEHD"}:
        audio_format = "TrueHD"
    elif audio_format in {"AAC", "A_AAC"}:
        audio_format = "AAC"
    elif audio_format == "FLAC":
        audio_format = "FLAC"
    elif audio_format == "OPUS":
        audio_format = "Opus"
    elif audio_format == "DTS":
        extra = " ".join(str(audio.get(key, "")) for key in ["Format_Profile", "Format_AdditionalFeatures", "CommercialName"]).upper()
        audio_format = "DTS-HD.MA" if "XLL" in extra or "MASTER AUDIO" in extra else "DTS-HD.HRA" if "HIGH RESOLUTION" in extra else "DTS"
    else:
        raise NamingError("Unsupported/unknown audio codec")
    channels = _number(audio.get("Channels"))
    layout = str(audio.get("ChannelLayout") or audio.get("ChannelPositions") or "")
    if channels < 1 or channels > 32:
        raise NamingError("Audio channel count is invalid")
    lfe = len(re.findall(r"\bLFE[12]?\b", layout, re.I))
    if not layout and channels > 2:
        raise NamingError("Multichannel layout is missing; do not guess 5.1 from six channels")
    if lfe > 2 or lfe >= channels:
        raise NamingError("Ambiguous LFE channel layout")
    channel_label = f"{channels - lfe}.{lfe}"
    audio_details = " ".join(str(audio.get(key, "")) for key in ["Format_Profile", "Format_AdditionalFeatures", "CommercialName", "Format_Commercial_IfAny"])
    atmos = bool(re.search(r"\bAtmos\b|\bJOC\b", audio_details, re.I))
    if atmos and audio_format not in {"DDP", "TrueHD"}:
        raise NamingError("Atmos signaling conflicts with the audio codec")
    hdr = " ".join(str(video.get(key, "")) for key in ["HDR_Format", "HDR_Format_String", "HDR_Format_Compatibility", "HDR_Format_Commercial"])
    dv = bool(re.search(r"Dolby\s*Vision", hdr, re.I))
    plus = bool(re.search(r"HDR10\s*\+|HDR10Plus|ST\s*2094[- ]40|ST\s*2094\s*App\s*4", hdr, re.I))
    hdr10 = bool(re.search(r"HDR10(?!\s*\+|Plus)", hdr, re.I))
    transfer = str(video.get("transfer_characteristics") or video.get("TransferCharacteristics") or "")
    if not (dv or plus or hdr10) and re.search(r"ST\s*2084|\bPQ\b|HLG|ARIB", transfer, re.I):
        raise NamingError("HDR transfer exists without a supported verified HDR label")
    labels = [title_token(title), str(year), f"{tier}p", provider, "WEB-DL", audio_format + channel_label]
    if atmos:
        labels.append("Atmos")
    if dv:
        labels.append("DV")
    if plus:
        labels.append("HDR10Plus")
    elif hdr10:
        labels.append("HDR10")
    labels.append(codec)
    name = ".".join(labels) + "-" + group + ".mkv"
    if len(name.encode("utf-8")) > 240:
        raise NamingError("Release name exceeds the safe filesystem component limit")
    return name
