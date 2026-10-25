"""Sanitizing private reference URLs must not yield reusable broken metadata."""
# ruff: noqa: S101
import asyncio

from src.meta import Meta
from src.runtime.prepared_stage import gather_with_resume
from src.temp_paths import release_temp_dir


def test_redacted_reference_urls_force_fresh_preparation(tmp_path):
    source = tmp_path/'movie.mkv'
    source.write_bytes(b'dummy')
    calls = []
    private_url = 'https://images.example/frame?token=example-private-value'
    class Prep:
        async def gather_prep(self, meta, **_kwargs):
            calls.append(True)
            meta.uuid = source.name
            meta.filelist = [str(source)]
            meta.image_list = [{'img_url':private_url,'raw_url':private_url,'web_url':private_url}]
            folder = release_temp_dir(meta.base_dir,meta.uuid)
            folder.mkdir(parents=True,exist_ok=True)
            (folder/'MEDIAINFO.txt').write_text('report')
            return meta
    def fresh():
        return Meta(base_dir=str(tmp_path),path=str(source),category='MOVIE')
    for _index in range(2):
        result = asyncio.run(gather_with_resume(Prep(),fresh(),mode='cli',config={'DEFAULT':{}}))
        assert result.image_list[0]['raw_url'] == private_url
    assert len(calls) == 2
    stored = (release_temp_dir(tmp_path,source.name)/'prepared_stage.json').read_text()
    assert 'example-private-value' not in stored
