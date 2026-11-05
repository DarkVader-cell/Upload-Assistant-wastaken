#!/usr/bin/env python3
"""Standalone dry-run-first release naming, privacy cleanup and real MKV remux."""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.catalogue_media import MediaError, _owned_path, planned_output, process_media
from src.media_naming import NamingError
from src.media_template import DEFAULT_TEMPLATE


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, help="Existing input file (or use --input)")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--root", type=Path, help="Owned input scope; defaults to the input parent")
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--output", type=Path, help="Explicit new MKV path; no standardized naming")
    output.add_argument("--output-dir", type=Path, help="Owned destination directory; derive the documented template filename")
    parser.add_argument("--output-root", type=Path, help="Owned output scope for an explicit destination outside the input scope")
    parser.add_argument("--title", help="Canonical movie title, not guessed from the old filename")
    parser.add_argument("--year", type=int)
    parser.add_argument("--provider", help="AMZN, NF, ATVP, DSNP, etc.; never guessed from a filename")
    parser.add_argument("--group", default="", help="Optional custom release-group tag; no fixed group is imposed")
    parser.add_argument("--template", default=DEFAULT_TEMPLATE, help="Documented Unshackle filename template; no extension")
    parser.add_argument("--original-language", help="Canonical original-language code for automatic primary audio selection")
    parser.add_argument("--naming-options-json", default="{}", help="Validated Unicode/codec/folder/group-rule naming settings")
    parser.add_argument("--tags-json", default="{}", help="Explicit editable MKV global tags JSON; writing application and identity tags are reserved")
    parser.add_argument("--audio-index", type=int, help="Optional explicit override of automatic original-language/first audio selection")
    parser.add_argument("--imdb", required=True)
    parser.add_argument("--tmdb", type=int, required=True)
    parser.add_argument("--filename-ids", action="store_true", help="Also place public IDs before the group suffix; tags always include IDs")
    parser.add_argument("--subtitle-language", action="append", default=[], metavar="TRACK_ID=CODE")
    parser.add_argument("--allow-linked-input", action="store_true", help="Explicitly allow read-only copying from a hardlinked input; never mutate its inode")
    parser.add_argument("--tool-bin", type=Path, help="Private MKVToolNix wrapper directory; system tools remain usable")
    cleanup_group = parser.add_mutually_exclusive_group()
    cleanup_group.add_argument("--cleanup-json", default="{}", help="Metadata selection JSON; default preserves fonts and unselected metadata")
    cleanup_group.add_argument("--strict-cleanup", action="store_true", help="Explicit legacy blanket cleanup, including attachment removal; not recommended for ASS fonts")
    parser.add_argument("--execute", action="store_true", help="Actually remux/verify; otherwise inspect and print a plan only")
    args = parser.parse_args(argv)
    os.umask(0o077)
    source = args.input or args.source
    if source is None or (args.input is not None and args.source is not None):
        parser.error("Provide exactly one input file")
    try:
        tool_bin = args.tool_bin
        default_bin = Path.home() / "apps/ua-catalogue/media-tools/current/bin"
        if tool_bin is None and default_bin.is_dir():
            tool_bin = default_bin
        if tool_bin is not None:
            tool_bin = tool_bin.resolve(strict=True)
            info = tool_bin.stat()
            if not tool_bin.is_dir() or info.st_uid not in {0, os.getuid()} or info.st_mode & 0o022:
                raise MediaError("Tool directory is not trusted")
            os.environ["PATH"] = str(tool_bin) + os.pathsep + os.environ.get("PATH", "")
        if not re.fullmatch(r"tt[0-9]{7,10}", args.imdb) or args.tmdb < 1:
            raise MediaError("Verified IMDb/TMDB IDs are required")
        from src.media_template import validate_options

        extra_tags = json.loads(args.tags_json)
        validate_options(tags=extra_tags)
        root = args.root or source.absolute().parent
        source = _owned_path(root, source)
        destination = args.output
        output_root = args.output_root
        if args.output_dir is not None:
            if not args.title or args.year is None or not args.provider:
                raise MediaError("Standard naming requires canonical --title, --year and --provider")
            output_root = output_root or args.output_dir
            naming = planned_output(
                source,
                args.title,
                args.year,
                args.provider,
                args.group,
                args.audio_index,
                args.template,
                original_language=args.original_language,
                naming_options=json.loads(args.naming_options_json),
            )
            name = naming["filename"]
            if args.filename_ids and args.template:
                raise MediaError("--filename-ids is not supported with custom templates; public IDs remain in MKV tags")
            if args.filename_ids:
                name = name.removesuffix(f"-{args.group}.mkv") + f".tmdb-{args.tmdb}.imdb-{args.imdb}-{args.group}.mkv"
            if len(name.encode("utf-8")) > 240:
                raise MediaError("Release name exceeds the safe filesystem component limit")
            destination = args.output_dir / naming["folder"] / name
        elif args.filename_ids:
            raise MediaError("--filename-ids requires standardized --output-dir naming")
        languages = {}
        for mapping in args.subtitle_language:
            track, separator, code = mapping.partition("=")
            if not separator or not track.isdigit() or track in languages:
                raise MediaError("Subtitle mappings must be unique numeric TRACK_ID=CODE entries")
            languages[track] = code
        report = process_media(
            root,
            source,
            destination,
            args.imdb,
            args.tmdb,
            languages,
            args.execute,
            privacy=True,
            allow_linked_input=args.allow_linked_input,
            output_root=output_root,
            extra_tags=extra_tags,
            cleanup=None if args.strict_cleanup else json.loads(args.cleanup_json),
        )
        print(json.dumps(report))
        return 0
    except (MediaError, OSError, ValueError) as error:
        reason = str(error) if isinstance(error, (MediaError, NamingError)) else "Naming, ownership or media verification failed; original retained"
        print(json.dumps({"ok": False, "reason": reason}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
