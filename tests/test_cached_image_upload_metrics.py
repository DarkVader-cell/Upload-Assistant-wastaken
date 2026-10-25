# ruff: noqa: S101
import asyncio
from unittest.mock import AsyncMock

from src.meta import Meta
from src.uploadscreens import UploadScreensManager


def test_restarted_cached_images_do_not_create_fake_network_uploads(tmp_path, monkeypatch):
    paths = [tmp_path/'one.png', tmp_path/'two.png']
    for path in paths:
        path.write_bytes(b'image')
    calls = []
    async def upload(args):
        calls.append(args[0])
        url = 'https://images.example/' + str(len(calls))
        return {'status':'success','img_url':url,'raw_url':url,'web_url':url}
    recorder = AsyncMock()
    monkeypatch.setattr('src.uploadscreens.upload_image_task', upload)
    monkeypatch.setattr('src.uploadscreens.record_event_async', recorder)
    monkeypatch.setattr('src.uploadscreens.manifest_files', lambda *_args: paths)
    manager = UploadScreensManager({'DEFAULT':{'img_host_1':'ptscreens'}})
    def fresh():
        return Meta(base_dir=str(tmp_path),uuid='release',imghost='ptscreens',image_list=[])
    asyncio.run(manager.upload_screens(fresh(),2,1,0,2,[],{}))
    assert len(calls) == 2
    recorder.reset_mock()
    result, count = asyncio.run(manager.upload_screens(fresh(),2,1,0,2,[],{}))
    assert len(result) == count == 2
    assert len(calls) == 2
    recorder.assert_not_awaited()
