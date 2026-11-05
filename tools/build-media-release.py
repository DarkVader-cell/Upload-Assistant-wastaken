#!/usr/bin/env python3
"""Build a standard-library-only standalone media-release.pyz (Python 3.11+)."""

import argparse
import os
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        parser.error("Refusing an existing output archive")
    with tempfile.TemporaryDirectory(prefix="media-release-build-") as directory:
        staging = Path(directory)
        (staging / "src").mkdir()
        (staging / "src/__init__.py").write_text("")
        for name in ["catalogue_media.py", "media_naming.py", "media_privacy.py", "media_template.py", "media_selection.py", "media_output.py"]:
            (staging / "src" / name).write_bytes((ROOT / "src" / name).read_bytes())
        (staging / "media_release_cli.py").write_bytes((ROOT / "tools/catalogue-media.py").read_bytes())
        (staging / "__main__.py").write_text("from media_release_cli import main\nraise SystemExit(main())\n")
        with args.output.open("xb") as output:
            zipapp.create_archive(staging, output, interpreter="/usr/bin/env python3", compressed=True)
            output.flush()
            os.fsync(output.fileno())
        args.output.chmod(0o700)
    print("Built standalone archive; external tools required: mkvmerge, mkvextract, mkvpropedit, ffmpeg, mediainfo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
