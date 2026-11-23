# ruff: noqa: S101

import asyncio
import os
from contextlib import contextmanager

import pytest

from src.queuemanage import QueueManager


@pytest.mark.parametrize(
    ("name", "is_directory", "extensions", "expected"),
    [
        ("movie.MKV", False, [".mkv"], True),
        ("notes.txt", False, [".mkv"], False),
        ("notes.txt", False, None, True),
        ("bdmv", True, [".mkv"], True),
        ("video_ts", True, [".mkv"], True),
        ("BDMV", False, [".mkv"], False),
        ("season.mkv", True, [".mkv"], False),
    ],
)
def test_should_include_directory_scans_once(tmp_path, monkeypatch, name, is_directory, extensions, expected):
    entry = tmp_path / name
    if is_directory:
        entry.mkdir()
    else:
        entry.touch()

    scandir = os.scandir
    scans = []

    @contextmanager
    def counted_scandir(path):
        scans.append(path)
        with scandir(path) as entries:
            yield entries

    monkeypatch.setattr(os, "scandir", counted_scandir)
    assert asyncio.run(QueueManager.should_include_directory(tmp_path, extensions)) is expected
    assert scans == [str(tmp_path)]
