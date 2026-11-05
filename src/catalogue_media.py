"""Conservative, non-destructive Matroska post-processing of owned downloads.

Never rewrites the input, transcodes streams, or invents a release filename.
Application metadata comes from a real mkvmerge remux, not a forged string.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from src.media_naming import release_name
from src.media_privacy import PrivacyError, safe_track_name, sanitized_chapters, verify_privacy
from src.media_selection import cleanup_options, verify_selection
from src.media_template import validate_options


class MediaError(RuntimeError):
    """Safe-to-display processing failure; original payload is retained."""


LANGUAGES = {
    "eng": "en",
    "hin": "hi",
    "tam": "ta",
    "tel": "te",
    "mal": "ml",
    "kan": "kn",
    "ben": "bn",
    "mar": "mr",
    "pan": "pa",
    "guj": "gu",
    "jpn": "ja",
    "kor": "ko",
    "chi": "zh",
    "zho": "zh",
    "fre": "fr",
    "fra": "fr",
    "ger": "de",
    "deu": "de",
    "spa": "es",
    "por": "pt",
    "ita": "it",
    "ara": "ar",
    "rus": "ru",
    "dut": "nl",
    "nld": "nl",
    "cze": "cs",
    "ces": "cs",
    "und": "und",
}


def language_code(value: str) -> str:
    """Normalize known ISO aliases and explicit BCP47, never guess unknown speech."""
    if not isinstance(value, str):
        raise MediaError("Subtitle language must be a code")
    parts = value.strip().replace("_", "-").split("-")
    primary = LANGUAGES.get(parts[0].lower(), parts[0].lower())
    if not re.fullmatch(r"[a-z]{2}|und", primary) or any(not re.fullmatch(r"[A-Za-z0-9]{2,8}", x) for x in parts[1:]):
        raise MediaError("Unsupported subtitle code; provide an explicit language mapping")
    return "-".join([primary, *[x.upper() if len(x) == 2 else x.title() if len(x) == 4 else x for x in parts[1:]]])


def cleaned_tags(xml: str, imdb: str, tmdb: int, extra_tags=None, remove_names=()) -> bytes:
    if not re.fullmatch(r"tt[0-9]{7,10}", imdb) or type(tmdb) is not int or tmdb <= 0:
        raise MediaError("Verified IMDb and TMDB identities are required")
    xml = re.sub(r"""<!DOCTYPE\s+Tags\s+SYSTEM\s+["']matroskatags\.dtd["']\s*>""", "", xml, flags=re.I)
    if len(xml) > 4 * 1024 * 1024 or "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise MediaError("Unsupported Matroska tags document")
    try:
        root = ET.fromstring(xml) if xml.strip() else ET.Element("Tags")
    except ET.ParseError:
        raise MediaError("Invalid Matroska tags document") from None
    if root.tag != "Tags":
        raise MediaError("Invalid Matroska tags root")
    for parent in list(root.iter()):
        global_parent = parent.tag == "Tag" and not any(
            target.tag in {"TrackUID", "ChapterUID", "AttachmentUID", "EditionUID"} for target in (parent.find("Targets") if parent.find("Targets") is not None else [])
        )
        for child in list(parent):
            if child.tag == "Simple" and (
                "cardinaldl" in (child.findtext("String") or "").casefold()
                or child.findtext("Name", "").upper() in {"IMDB", "TMDB", "IMDB_ID", "TMDB_ID", *remove_names}
                or (global_parent and child.findtext("Name", "").upper() in (extra_tags or {}))
            ):
                parent.remove(child)
    # mkvmerge requires at least one Simple per Tag, including targeted tags.
    # Removing/replacing the last selected value must not leave an empty shell.
    for existing in list(root.findall("Tag")):
        if not existing.findall("Simple"):
            root.remove(existing)
    tag = ET.SubElement(root, "Tag")
    ET.SubElement(tag, "Targets")
    extra_tags = validate_options(tags=extra_tags)["tags"]
    for name, value in [("IMDB", imdb), ("TMDB", str(tmdb)), *extra_tags.items()]:
        simple = ET.SubElement(tag, "Simple")
        ET.SubElement(simple, "Name").text = name
        ET.SubElement(simple, "String").text = value
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _run(arguments, timeout=120):
    if not arguments or arguments[0] not in {"mkvmerge", "mkvextract", "mkvpropedit", "ffmpeg", "mediainfo"}:
        raise MediaError("Unsupported media tool")
    try:
        if shutil.which(arguments[0]) is None and arguments[0] in {"mkvmerge", "mkvextract", "mkvpropedit"}:
            tools = (Path.home() / "apps/ua-catalogue/media-tools/current/bin").resolve(strict=True)
            info = tools.stat()
            if info.st_uid not in {0, os.getuid()} or info.st_mode & 0o022:
                raise MediaError("Private media tools are not trusted")
            arguments = [str(tools / arguments[0]), *arguments[1:]]
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, check=False)  # noqa: S603 -- allowlisted tools, argv only, guarded owned paths
    except (OSError, subprocess.TimeoutExpired):
        raise MediaError("Media tool unavailable or timed out; original retained") from None
    # mkvmerge exit 1 means warnings, not success: fail closed for automatic use.
    if result.returncode != 0:
        raise MediaError("Media tool failed or reported warnings; original retained")
    if len(result.stdout) > 8 * 1024 * 1024:
        raise MediaError("Media tool report exceeded limit")
    return result.stdout


def _identify(path):
    try:
        return json.loads(_run(["mkvmerge", "-J", str(path)]))
    except ValueError:
        raise MediaError("Invalid mkvmerge identity report") from None


def _owned_path(root: Path, path: Path, exists=True):
    root = root.absolute()
    path = path.absolute()
    if ".." in root.parts or ".." in path.parts or root.resolve() != root:
        raise MediaError("Non-canonical or symlinked job directory refused")
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise MediaError("Media path escapes the explicitly owned job directory") from None
    current = root
    for part in (None, *relative.parts):
        if part is not None:
            current = current / part
        if not current.exists() and current != root and not exists:
            if current.is_symlink():
                raise MediaError("Dangling symlinked media path refused")
            continue
        st = current.lstat()
        if stat.S_ISLNK(st.st_mode) or st.st_uid != os.getuid():
            raise MediaError("Symlinked or foreign-owned media path refused")
        if current != path and (not stat.S_ISDIR(st.st_mode) or st.st_mode & 0o022):
            raise MediaError("Job directory must not be writable by other users")
    return path


def _stream_signature(report):
    return [
        (
            track.get("type"),
            track.get("codec"),
            {
                key: value
                for key, value in track.get("properties", {}).items()
                if key
                in {
                    "codec_id",
                    "codec_private_data",
                    "codec_private_length",
                    "pixel_dimensions",
                    "display_dimensions",
                    "audio_channels",
                    "audio_sampling_frequency",
                    "max_block_addition_id",
                }
                or key.startswith(("color_", "dolby_vision"))
            },
        )
        for track in report.get("tracks", [])
    ]


def planned_output(source, title, year, provider, group="", audio_index=None, template=None, *, original_language=None, naming_options=None, title_data=None):
    from src.media_output import context, format_name

    if not isinstance(title, str) or not title.strip() or len(title) > 300 or type(year) is not int or not 1870 <= year <= 2100:
        raise MediaError("A valid canonical title/year is required")
    if not isinstance(provider, str) or not re.fullmatch(r"[A-Za-z0-9+_-]{1,32}", provider):
        raise MediaError("A safe explicit source label is required")
    try:
        info = json.loads(_run(["mediainfo", "--Output=JSON", str(source)]))
    except ValueError:
        raise MediaError("Invalid MediaInfo report; no release name can be inferred") from None
    if template is None:
        return {"filename": release_name(info, title, year, provider, group, audio_index), "folder": "", "context": {}}
    options = validate_options(**{**(naming_options or {}), "group": group, "template": template, "tags": {}})
    values = context(info, title, year, provider, group, original_language, audio_index, options, title_data)
    name = format_name(template, values, options["unicode_filenames"]) + ".mkv"
    if len(name.encode("utf-8")) > 240:
        raise MediaError("Output filename exceeds the safe component limit")
    folder_template = options["folder_template"]
    folder_values = dict(values)
    folder_values["part"] = ""
    data = title_data or {}
    if data.get("title_type") in {"series", "sports"}:
        folder_values.update(episode=f"E{data['episode']:02d}", season_episode=f"S{data['season']:02d}E{data['episode']:02d}")
        if data.get("date"):
            air_year = str(data["date"])[:4]
            folder_values["season"] = air_year
            folder_values["year"] = "" if str(year) == air_year else year
        if not folder_template:
            folder_template = re.sub(r"\{episode\}|\{episode_name\??\}", "", template).replace("{season_episode}", "{season}")
    folder = ""
    if folder_template:
        between = "".join(re.findall(r"\}([^{}]*)\{", folder_template))
        spacer = " " if between.count(" ") > between.count(".") else "."
        parts = [format_name(part, folder_values, options["unicode_filenames"], spacer) for part in re.split(r"[/\\\\]", folder_template) if part.strip()]
        if len(parts) > 8 or any(len(part.encode()) > 240 or part in {".", ".."} for part in parts):
            raise MediaError("Output folder template is too deep or unsafe")
        folder = "/".join(parts)
    return {"filename": name, "folder": folder, "context": values}


def planned_release_name(source: Path, title: str, year: int, provider: str, group="Kitsune", audio_index=None, template=None, **kwargs) -> str:
    return planned_output(source, title, year, provider, group, audio_index, template, **kwargs)["filename"]


def process_media(
    root: Path,
    source: Path,
    destination: Path,
    imdb: str,
    tmdb: int,
    subtitle_languages=None,
    execute=False,
    *,
    privacy=True,
    allow_linked_input=False,
    output_root=None,
    extra_tags=None,
    cleanup=None,
) -> dict:
    """Explicit existing-file target; safe copy/remux, never an in-place edit."""
    requested_privacy = privacy
    selective = cleanup is not None
    cleanup = cleanup_options(cleanup) if selective else None
    if selective:
        privacy = False
    root = Path(root)
    source = _owned_path(root, Path(source))
    destination = _owned_path(Path(output_root) if output_root is not None else root, Path(destination), exists=False)
    before = source.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink < 1 or (before.st_nlink != 1 and not allow_linked_input) or source.suffix.lower() not in {".mkv", ".mp4"}:
        raise MediaError("Only owned regular MKV/MP4 payloads may be processed; linked inputs require explicit read-only consent")
    if source == destination or destination.exists() or destination.is_symlink() or destination.suffix.lower() != ".mkv":
        raise MediaError("A new non-existing MKV destination is required; input is never overwritten")
    if selective:
        extra_tags = validate_options(tags={**(extra_tags or {}), **cleanup["tag_edits"]})["tags"]
    tags = cleaned_tags("", imdb, tmdb, extra_tags)  # Validate IDs before invoking tools.
    report = _identify(source)
    tracks = report.get("tracks", [])
    if selective and (
        (set(cleanup["remove_track_names"]) | set(cleanup["track_overrides"])) - {str(t["id"]) for t in tracks}
        or set(cleanup["remove_attachment_ids"]) - {str(a["id"]) for a in report.get("attachments", [])}
    ):
        raise MediaError("Selection references an unknown track or attachment")
    if not any(x.get("type") == "video" for x in tracks) or not any(x.get("type") == "audio" for x in tracks):
        raise MediaError("Audio/video payload verification failed")
    languages = {}
    overrides = subtitle_languages or {}
    if not isinstance(overrides, dict) or any(not isinstance(key, str) for key in overrides):
        raise MediaError("Subtitle mappings require string track IDs")
    subtitle_ids = {str(t["id"]) for t in tracks if t.get("type") == "subtitles"}
    if set(overrides) - subtitle_ids:
        raise MediaError("Subtitle mapping references a non-subtitle or unknown track")
    arguments = []
    title = report.get("container", {}).get("properties", {}).get("title")
    if selective and cleanup["container_title"] is not None:
        arguments.extend(["--title", cleanup["container_title"]])
    elif privacy or (selective and cleanup["clear_title"]):
        arguments.extend(["--title", ""])
    elif isinstance(title, str) and "cardinaldl" in title.casefold():
        arguments.extend(["--title", re.sub(r"\bcardinaldl\b", "", title, flags=re.I).strip(" -_[]()")])
    track_names = {}
    for track in tracks:
        properties = track.get("properties", {})
        track_id = str(track["id"])
        edits = cleanup["track_overrides"].get(track_id, {}) if selective else {}
        for field, flag in [
            ("default", "--default-track-flag"),
            ("forced", "--forced-display-flag"),
            ("hearing_impaired", "--hearing-impaired-flag"),
            ("commentary", "--commentary-flag"),
        ]:
            if field in edits:
                arguments.extend([flag, f"{track_id}:{int(edits[field])}"])
        if "language" in edits:
            languages[track_id] = language_code(edits["language"])
            arguments.extend(["--language", f"{track_id}:{languages[track_id]}"])
        elif track.get("type") == "subtitles":
            original = overrides.get(track_id, properties.get("language_ietf") or properties.get("language") or "und")
            languages[track_id] = language_code(original)
            arguments.extend(["--language", f"{track_id}:{languages[track_id]}"])
        name = properties.get("track_name")
        if "name" in edits:
            arguments.extend(["--track-name", f"{track_id}:{edits['name']}"])
        elif privacy:
            original_language = languages.get(track_id) or properties.get("language_ietf") or properties.get("language") or "und"
            if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", original_language):
                raise MediaError("Track language is not a safe standardized code")
            track_names[track_id] = safe_track_name(track, languages.get(track_id) or original_language)
            arguments.extend(["--track-name", f"{track_id}:{track_names[track_id]}"])
        elif selective and track_id in cleanup["remove_track_names"]:
            arguments.extend(["--track-name", f"{track_id}:"])
        elif isinstance(name, str) and "cardinaldl" in name.casefold():
            cleaned = re.sub(r"\bcardinaldl\b", "", name, flags=re.I).strip(" -_[]()")
            arguments.extend(["--track-name", f"{track_id}:{cleaned}"])
    summary = {
        "schema": 1,
        "source": str(source),
        "output": str(destination),
        "imdb": imdb,
        "tmdb": tmdb,
        "subtitle_languages": languages,
        "original_retained": True,
        "executed": False,
        "naming_policy": "explicit target or verified MediaInfo template output",
        "privacy_sanitized": False,
        "privacy_requested": requested_privacy,
        "cleanup_mode": "selected" if selective else "strict",
        "metadata_selection_verified": False,
        "attachments_to_remove": len(cleanup["remove_attachment_ids"]) if selective else len(report.get("attachments", [])) if privacy else 0,
        "linked_input_read_only": before.st_nlink > 1,
        "privacy_limit": "Container metadata only; no guarantee against in-band identifiers, forensic watermarks or audiovisual identifying content",
    }
    if not execute:
        return summary
    chapters = None
    if source.suffix.lower() == ".mkv":
        if not privacy:
            tags = cleaned_tags(_run(["mkvextract", str(source), "tags"]).decode("utf-8"), imdb, tmdb, extra_tags, cleanup["remove_tag_names"] if selective else ())
            if selective and cleanup["clear_chapter_names"] and report.get("chapters"):
                chapters = sanitized_chapters(_run(["mkvextract", str(source), "chapters"]).decode("utf-8"))
        elif report.get("chapters"):
            try:
                chapters = sanitized_chapters(_run(["mkvextract", str(source), "chapters"]).decode("utf-8"))
            except PrivacyError as error:
                raise MediaError(str(error)) from None
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _owned_path(Path(output_root) if output_root is not None else root, destination.parent)
    with tempfile.TemporaryDirectory(prefix=".ua-remux-", dir=destination.parent) as temporary:
        temporary = Path(temporary)
        temporary.chmod(0o700)
        tag_path = temporary / "tags.xml"
        tag_path.write_bytes(tags)
        tag_path.chmod(0o600)
        output = temporary / "payload.mkv"
        global_options = []
        input_options = ["--no-global-tags", "--no-track-tags"]
        if selective:
            global_options.append("--disable-track-statistics-tags")
            if cleanup["remove_dates"]:
                global_options.append("--no-date")
            if cleanup["remove_attachment_ids"]:
                keep = [str(a["id"]) for a in report.get("attachments", []) if str(a["id"]) not in cleanup["remove_attachment_ids"]]
                input_options.extend(["--attachments", ",".join(keep)] if keep else ["--no-attachments"])
            if chapters is not None:
                chapter_path = temporary / "chapters.xml"
                chapter_path.write_bytes(chapters)
                input_options.append("--no-chapters")
                global_options.extend(["--chapters", str(chapter_path)])
        if privacy:
            global_options.extend(["--no-date", "--disable-track-statistics-tags", "--segment-uid", secrets.token_hex(16)])
            input_options.extend(["--no-attachments", "--no-chapters"])
            if chapters is not None:
                chapter_path = temporary / "chapters.xml"
                chapter_path.write_bytes(chapters)
                chapter_path.chmod(0o600)
                global_options.extend(["--chapters", str(chapter_path)])
        _run(["mkvmerge", "--output", str(output), *global_options, "--global-tags", str(tag_path), *arguments, *input_options, str(source)], timeout=7200)
        if privacy:
            # Older mkvmerge releases preserve source track UIDs. Edit ONLY our
            # new private output through mkvpropedit (which maintains EBML CRCs).
            generated = _identify(output)
            used = {str(track.get("properties", {}).get("uid")) for track in tracks}
            uid_arguments = ["mkvpropedit", str(output)]
            for track in generated.get("tracks", []):
                number = track.get("properties", {}).get("number")
                if type(number) is not int or number < 1:
                    raise MediaError("Output track number is unavailable for safe UID regeneration")
                new_uid = str(secrets.randbits(63) + 1)
                while new_uid in used:
                    new_uid = str(secrets.randbits(63) + 1)
                used.add(new_uid)
                uid_arguments.extend(["--edit", f"track:@{number}", "--set", f"track-uid={new_uid}"])
            _run(uid_arguments)
        result = _identify(output)
        if _stream_signature(report) != _stream_signature(result):
            raise MediaError("Stream/HDR identity changed during remux; original retained")
        for old, new in zip(tracks, result.get("tracks", []), strict=True):
            a, b = old.get("properties", {}), new.get("properties", {})
            edits = cleanup["track_overrides"].get(str(old["id"]), {}) if selective else {}
            editable_flags = {
                "default": ("default_track",),
                "forced": ("forced_track",),
                "hearing_impaired": ("hearing_impaired", "flag_hearing_impaired"),
                "commentary": ("commentary", "flag_commentary"),
            }
            changed = {key for field, aliases in editable_flags.items() if field in edits for key in aliases}
            for field, aliases in editable_flags.items():
                if field in edits and next((b[key] for key in aliases if key in b), False) != edits[field]:
                    raise MediaError("Requested track flag was not applied")
            if any(
                a.get(flag) != b.get(flag)
                for flag in [
                    "default_track",
                    "forced_track",
                    "hearing_impaired",
                    "flag_hearing_impaired",
                    "flag_visual_impaired",
                    "flag_text_descriptions",
                    "flag_original",
                    "flag_commentary",
                ]
                if flag not in changed
            ):
                raise MediaError("Track flags changed during remux")
            if str(old["id"]) in languages and language_code(b.get("language_ietf") or b.get("language") or "und") != languages[str(old["id"])]:
                raise MediaError("Subtitle language verification failed")
        actual_tags = _run(["mkvextract", str(output), "tags"]).decode("utf-8")
        tag_root = ET.fromstring(actual_tags)
        values = {(x.findtext("Name"), x.findtext("String")) for x in tag_root.iter("Simple")}
        if ("IMDB", imdb) not in values or ("TMDB", str(tmdb)) not in values or "cardinaldl" in actual_tags.casefold():
            raise MediaError("Identity or branding verification failed")
        writing = result.get("container", {}).get("properties", {}).get("writing_application", "")
        if "mkvmerge" not in writing.casefold():
            raise MediaError("Real mkvmerge writing application was not verified")
        if privacy:
            try:
                verify_privacy(report, result, actual_tags, imdb, tmdb, track_names, extra_tags)
            except PrivacyError as error:
                raise MediaError(str(error)) from None
        if selective:
            try:
                verify_selection(report, result, cleanup, actual_tags, imdb, tmdb, extra_tags)
            except ValueError as error:
                raise MediaError(str(error)) from None
        # Copy-stream hashes verify actual audio/video payloads, not just an exit
        # code or track count. No decoder, encoder or quality conversion is used.
        hashes = [
            _run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v", "-map", "0:a?", "-c", "copy", "-f", "streamhash", "-hash", "sha256", "-"], timeout=7200)
            for path in (source, output)
        ]
        if not hashes[0] or hashes[0] != hashes[1]:
            raise MediaError("Audio/video packet hashes changed during remux; original retained")
        current = source.stat()
        if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns, current.st_nlink) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_nlink,
        ):
            raise MediaError("Input changed during remux; output not published")
        output.chmod(0o600)
        if privacy or (selective and cleanup["remove_dates"]):
            os.utime(output, ns=(0, 0))  # Do not export the processing time as mtime.
        # link is atomic and refuses an existing destination, unlike replace.
        try:
            os.link(output, destination)
        except OSError:
            raise MediaError("Output could not be published without overwriting; original retained") from None
        summary.update(
            executed=True,
            writing_application=writing,
            bytes=destination.stat().st_size,
            stream_identity_verified=True,
            audio_video_hashes_verified=True,
            privacy_sanitized=privacy,
            metadata_selection_verified=selective,
        )
    return summary
