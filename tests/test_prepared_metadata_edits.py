# ruff: noqa: S101
import asyncio

from src.meta import Meta
from src.runtime.prepared_stage import PreparedStage, refresh_prepared_metadata
from src.temp_paths import release_temp_dir


def test_confirmed_metadata_survives_but_force_permissions_do_not(tmp_path):
    source = tmp_path / 'movie.mkv'
    source.write_bytes(b'dummy')
    def fresh():
        return Meta(base_dir=str(tmp_path), path=str(source), uuid=source.name, category='MOVIE', filelist=[str(source)])
    meta = fresh()
    checkpoint = PreparedStage(meta, {'DEFAULT': {}})
    directory = release_temp_dir(tmp_path, source.name)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'MEDIAINFO.txt').write_text('report')
    meta.title = 'Original lookup'
    checkpoint.save(meta)
    meta.title = 'User corrected title'
    meta.dupe = True
    meta.confirm_not_uploaded = ['AITHER:old-confirmation']
    asyncio.run(refresh_prepared_metadata(meta))
    restored = PreparedStage(fresh(), {'DEFAULT': {}}).load()
    assert restored['title'] == 'User corrected title'
    assert restored.get('dupe') is not True
    assert 'confirm_not_uploaded' not in restored
    assert (checkpoint.path.stat().st_mode & 0o777) == 0o600
