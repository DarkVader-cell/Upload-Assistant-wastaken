"""Synthetic preparation restarts: no sockets, tracker requests or payload writes."""
# ruff: noqa: S101
import asyncio
from pathlib import Path

import pytest

from src.meta import Meta
from src.runtime.prepared_stage import PreparationSourceChangedError, gather_with_resume
from src.temp_paths import release_temp_dir


class Prep:
    def __init__(self):
        self.calls = 0

    async def gather_prep(self, meta, mode):
        _ = mode
        self.calls += 1
        meta.uuid = Path(meta.path).name
        meta.filelist = [meta.path]
        meta.title = 'Prepared title'
        meta.tracker_status = {'AITHER': {'upload': True}}
        directory = release_temp_dir(meta.base_dir, meta.uuid)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'MEDIAINFO.txt').write_text('synthetic report')
        return meta


def test_resume_reuses_preparation_not_tracker_permission(tmp_path):
    source = tmp_path / 'input.mkv'
    source.write_bytes(b'dummy')
    prep = Prep()
    def fresh(**kwargs):
        return Meta(path=str(source), base_dir=str(tmp_path), category='MOVIE', trackers=['AITHER'], **kwargs)
    asyncio.run(gather_with_resume(prep, fresh(), mode='cli', config={'DEFAULT': {}}))
    resumed = asyncio.run(gather_with_resume(prep, fresh(), mode='cli', config={'DEFAULT': {}}))
    assert prep.calls == 1
    assert resumed.title == 'Prepared title'
    assert not resumed.tracker_status
    assert resumed.trackers == ['AITHER']
    # Adding a legitimate tracker hardlink changes ctime, not the media bytes.
    (tmp_path / 'tracker-hardlink.mkv').hardlink_to(source)
    asyncio.run(gather_with_resume(prep, fresh(), mode='cli', config={'DEFAULT': {}}))
    assert prep.calls == 1
    source.write_bytes(b'changed payload')
    with pytest.raises(PreparationSourceChangedError, match='fingerprint changed'):
        asyncio.run(gather_with_resume(prep, fresh(), mode='cli', config={'DEFAULT': {}}))
    assert prep.calls == 1


def test_force_options_and_missing_artifact_regather(tmp_path):
    source = tmp_path / 'input.mkv'
    source.write_bytes(b'dummy')
    prep = Prep()
    def fresh(**kw):
        return Meta(path=str(source), base_dir=str(tmp_path), category='MOVIE', **kw)
    for flags in ({}, {'delete_meta': True}, {}):
        asyncio.run(gather_with_resume(prep, fresh(**flags), mode='cli', config={'DEFAULT': {}}))
    assert prep.calls == 2
    (release_temp_dir(tmp_path, source.name) / 'MEDIAINFO.txt').unlink()
    asyncio.run(gather_with_resume(prep, fresh(), mode='cli', config={'DEFAULT': {}}))
    assert prep.calls == 3
