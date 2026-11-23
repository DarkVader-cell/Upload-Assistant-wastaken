# ruff: noqa: S101
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.meta import Meta
from src.torrentcreate import TorrentCreator


@pytest.mark.parametrize("allow_subs", [False, True])
def test_mkbrr_directory_preflight_measures_excluded_files(tmp_path: Path, allow_subs: bool) -> None:
    selected = tmp_path / "episode.mkv"
    selected.write_bytes(b"film")
    nested = tmp_path / "extras"
    nested.mkdir()
    for name in ("z.mkv", "a.mkv", "notes.txt", "caption.srt"):
        (nested / name).write_bytes(b"123")

    size, exclusions = TorrentCreator._mkbrr_directory_preflight(str(tmp_path), [str(selected)], allow_subs)

    assert size == 16
    if allow_subs:
        assert exclusions == "a.mkv,caption.srt,z.mkv,*.nfo,*.jpg,*.png,*.txt,*.xml"
    else:
        assert exclusions == "a.mkv,z.mkv,*.nfo,*.jpg,*.png,*.srt,*.sub,*.vtt,*.ssa,*.ass,*.txt,*.xml"


def test_mkbrr_directory_preflight_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "release"
    root.mkdir()
    selected = root / "episode.mkv"
    selected.write_bytes(b"film")
    external = tmp_path / "other"
    external.mkdir()
    (external / "extra.mkv").write_bytes(b"extra")
    try:
        (root / "alias.mkv").symlink_to(selected)
        (root / "broken.mkv").symlink_to(root / "missing")
        (root / "directory").symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    size, exclusions = TorrentCreator._mkbrr_directory_preflight(str(root), [str(selected)], False)

    assert size == 8  # count the linked regular file too, but not the dangling link or linked directory
    assert exclusions == "broken.mkv,*.nfo,*.jpg,*.png,*.srt,*.sub,*.vtt,*.ssa,*.ass,*.txt,*.xml"


@pytest.mark.asyncio
@pytest.mark.parametrize(("keep", "drop"), [("Episode.mkv", "episode.MKV"), ("film.mkv", "sample,[A].mkv"), ("notes.TXT", "extra.mkv")])
async def test_mkbrr_directory_fallback_after_one_walk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keep: str, drop: str) -> None:
    selected = tmp_path / keep
    selected.write_bytes(b"keep")
    extras = tmp_path / "extras"
    extras.mkdir()
    (extras / drop).write_bytes(b"unselected")
    meta = Meta(base_dir=str(tmp_path), category="MOVIE", filelist=[str(selected)], keep_folder=True, mkbrr=True)
    walk = Mock(wraps=os.walk)
    monkeypatch.setattr("src.torrentcreate.os.walk", walk)
    monkeypatch.setattr(TorrentCreator, "get_mkbrr_path", lambda _: pytest.fail("unsafe exclusion should bypass mkbrr"))
    # Stop at torf piece sizing: the backend's own filesystem access is not preflight.
    piece_size = Mock(side_effect=RuntimeError("reached torf"))
    monkeypatch.setattr(TorrentCreator, "calculate_piece_size", piece_size)

    with pytest.raises(RuntimeError, match="reached torf"):
        await TorrentCreator.create_torrent(meta, tmp_path, "BASE")

    walk.assert_called_once_with(str(tmp_path))
    assert piece_size.call_args.args[0] == 14
    assert meta.mkbrr  # unsafe exclusions fall back only for this torrent
