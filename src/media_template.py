"""Safe movie output templates using the documented Unshackle variable syntax.

Not an Unshackle runtime or its full TV/music template engine. No expressions,
attribute access, paths, or format-spec evaluation are accepted.
"""

from __future__ import annotations

import re
import unicodedata

from src.media_output import FIELDS

DEFAULT_TEMPLATE = "{title}.{year}.{quality}.{source}.WEB-DL.{audio_full}.{video}-{tag}"

VARIABLES = FIELDS
NAMING_KEYS = ('unicode_filenames','codec_names','folder_template','tag_rules','dual_multi_mode','no_source')
PLACEHOLDER = re.compile(r"\{([a-z_]+)(\?)?\}")


def validate_options(
    group="", template=DEFAULT_TEMPLATE, tags=None, unicode_filenames=False, codec_names=None, folder_template="", tag_rules=None, dual_multi_mode="strict", no_source=False
):
    if not isinstance(group, str) or not re.fullmatch(r"[A-Za-z0-9_-]{0,32}", group):
        raise ValueError("Release group must be 0-32 letters, digits, underscores or hyphens")
    if not isinstance(template, str) or not 1 <= len(template) <= 300 or any(c in template for c in '/\\<>:"|*\r\n\x00'):
        raise ValueError("Filename template must be a safe single filename component")
    remaining = PLACEHOLDER.sub("", template)
    if any(c in remaining for c in "{}?") or any(m[1] not in VARIABLES for m in PLACEHOLDER.finditer(template)):
        raise ValueError("Unknown or unsupported movie template variable")
    if "{title}" not in template and "{title?}" not in template:
        raise ValueError("Template must include {title}")
    tags = {} if tags is None else tags
    reserved = {
        "IMDB",
        "TMDB",
        "IMDB_ID",
        "TMDB_ID",
        "ENCODER",
        "ENCODER_SETTINGS",
        "WRITING_APPLICATION",
        "MUXING_APPLICATION",
        "DURATION",
        "BPS",
        "NUMBER_OF_FRAMES",
        "NUMBER_OF_BYTES",
        "FRAME_RATE",
        "WIDTH",
        "HEIGHT",
        "CODEC",
        "CODEC_ID",
    }
    if not isinstance(tags, dict) or len(tags) > 64:
        raise ValueError("Invalid MKV tag object")
    for name, value in tags.items():
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", name)
            or name in reserved
            or name.startswith("_STATISTICS")
            or not isinstance(value, str)
            or len(value) > 1000
            or any(ord(c) < 32 and c not in "\n\t" for c in value)
            or "cardinaldl" in value.casefold()
        ):
            raise ValueError("Unsupported tag/value; application and identity tags cannot be forged")
    if type(unicode_filenames) is not bool or type(no_source) is not bool or dual_multi_mode not in {"strict", "count"}:
        raise ValueError("Invalid filename settings")
    codec_names = {} if codec_names is None else codec_names
    if (
        not isinstance(codec_names, dict)
        or len(codec_names) > 64
        or any(
            not isinstance(key, str) or len(key) > 60 or (value is not None and (not isinstance(value, str) or len(value) > 60 or any(c in value for c in '/\\\\<>:"|?*\r\n')))
            for key, value in codec_names.items()
        )
    ):
        raise ValueError("Invalid codec label overrides")
    if (
        not isinstance(folder_template, str)
        or len(folder_template) > 500
        or folder_template.startswith(("/", "\\\\"))
        or any(part == ".." for part in re.split(r"[/\\\\]", folder_template))
    ):
        raise ValueError("Folder template must stay within the selected output root")
    if any(match[1] not in VARIABLES for match in PLACEHOLDER.finditer(folder_template)) or any(char in PLACEHOLDER.sub("", folder_template) for char in "{}"):
        raise ValueError("Invalid folder-template variable")
    tag_rules = [] if tag_rules is None else tag_rules
    allowed_rules = {
        "title_type",
        "quality",
        "resolution",
        "source",
        "video",
        "hdr",
        "hfr",
        "audio",
        "audio_channels",
        "audio_full",
        "atmos",
        "dual",
        "multi",
        "dubbed",
        "edition",
        "repack",
        "lang_tag",
    }
    if not isinstance(tag_rules, list) or len(tag_rules) > 32:
        raise ValueError("Invalid release-group rules")
    for rule in tag_rules:
        if (
            not isinstance(rule, dict)
            or set(rule) != {"when", "tag"}
            or not isinstance(rule["when"], dict)
            or not rule["when"]
            or set(rule["when"]) - allowed_rules
            or not isinstance(rule["tag"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{0,32}", rule["tag"])
        ):
            raise ValueError("Invalid release-group rule")
        if any(
            not isinstance(value, (str, int, bool, list)) or (isinstance(value, list) and (len(value) > 32 or any(not isinstance(v, (str, int, bool)) for v in value)))
            for value in rule["when"].values()
        ):
            raise ValueError("Invalid rule conditions")
    return {
        "group": group,
        "template": template,
        "tags": tags,
        "unicode_filenames": unicode_filenames,
        "codec_names": codec_names,
        "folder_template": folder_template,
        "tag_rules": tag_rules,
        "dual_multi_mode": dual_multi_mode,
        "no_source": no_source,
    }


def render_movie(legacy_name, title, year, provider, group="", template=DEFAULT_TEMPLATE):
    """Derive all technical variables from the existing verified MediaInfo name."""
    validate_options(group, template)
    # Core release_name is the sole authority for stream characteristics.
    match = re.search(
        r"\.(\d+p)\." + re.escape(provider) + r"\.WEB-DL\.(DDP|DD|TrueHD|AAC|FLAC|Opus|DTS-HD\.MA|DTS-HD\.HRA|DTS)(\d+\.\d+)(.*?)\.(H\.264|H\.265|AV1)-TEMPLATE\.mkv$",
        legacy_name,
    )
    if not match:
        raise ValueError("Verified media name could not supply template variables")
    quality, audio, channels, extras, video = match.groups()
    dv = ".DV" in extras
    plus = ".HDR10Plus" in extras
    hdr10 = ".HDR10" in extras and not plus
    hdr = "DV.HDR10P" if dv and plus else "DV.HDR" if dv and hdr10 else "DV" if dv else "HDR10P" if plus else "HDR" if hdr10 else ""
    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    normalized = re.sub(r"['\u2019]", "", normalized)
    separators = PLACEHOLDER.sub("", template)
    separator = " " if separators.count(" ") > separators.count(".") else "."
    normalized = re.sub(r"[^\w-]+", separator, normalized.replace("$", "S")).strip(" .-_")
    if not normalized:
        raise ValueError("Title cannot be represented safely in ASCII; supply a title override")
    values = {
        "title": normalized,
        "year": str(year),
        "quality": quality,
        "resolution": quality[:-1],
        "source": provider,
        "tag": group,
        "audio": audio,
        "audio_channels": channels,
        "audio_full": audio + channels,
        "atmos": "Atmos" if ".Atmos" in extras else "",
        "video": video,
        "hdr": hdr,
        "title_type": "movie",
    }
    tokens = []
    position = 0
    for field in PLACEHOLDER.finditer(template):
        tokens.append(template[position : field.start()])
        value = values[field[1]]
        if not value:
            if not field[2] and field[1] != "tag":
                raise ValueError("Required filename field is empty; mark it optional with ?")
            if tokens[-1] and tokens[-1][-1] in ". _-":
                tokens[-1] = tokens[-1][:-1]
            elif field.end() < len(template) and template[field.end()] in ". _-":
                tokens.append("")
                position = field.end() + 1
                continue
        tokens.append(value)
        position = field.end()
    tokens.append(template[position:])
    name = "".join(tokens).strip(" .-_")
    if not name or name in {".", ".."} or any(c in name for c in '/\\<>:"|?*\r\n\x00') or len((name + ".mkv").encode()) > 240:
        raise ValueError("Rendered filename is unsafe or too long")
    return name + ".mkv"
