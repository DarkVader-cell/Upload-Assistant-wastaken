# ruff: noqa: S101
import asyncio

from src.meta import Meta
from src.runtime.prepared_stage import gather_with_resume
from src.temp_paths import release_temp_dir


def test_resumed_metadata_resolves_current_default_trackers(tmp_path):
    source = tmp_path / 'movie.mkv'
    source.write_bytes(b'dummy')
    calls = []
    class Prep:
        async def gather_prep(self, meta, **_kwargs):
            calls.append('prepare')
            meta.uuid = source.name
            meta.filelist = [str(source)]
            directory = release_temp_dir(meta.base_dir,meta.uuid)
            directory.mkdir(parents=True,exist_ok=True)
            (directory/'MEDIAINFO.txt').write_text('report')
            return meta
    def fresh():
        return Meta(base_dir=str(tmp_path),path=str(source),category='MOVIE')
    config = {'DEFAULT':{},'TRACKERS':{'default_trackers':'AITHER'}}
    asyncio.run(gather_with_resume(Prep(),fresh(),mode='cli',config=config))
    resumed = asyncio.run(gather_with_resume(Prep(),fresh(),mode='cli',config=config))
    assert resumed.trackers == ['AITHER']
    assert len(calls) == 1
    config['TRACKERS']['default_trackers'] = 'LST'
    asyncio.run(gather_with_resume(Prep(),fresh(),mode='cli',config=config))
    assert len(calls) == 2
