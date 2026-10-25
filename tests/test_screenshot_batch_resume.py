# ruff: noqa: S101
import asyncio
from pathlib import Path

from src.meta import Meta
from src.uploadscreens import _upload_screens


def test_completed_siblings_survive_host_failure_and_restart(tmp_path, monkeypatch):
    calls = []
    for i in range(3):
        (tmp_path / f'image-{i}.png').write_bytes(b'dummy image')
    config = {'DEFAULT': {'img_host_1':'lostimg', 'img_host_2':'ptscreens', 'image_upload_concurrency':3, 'image_upload_delay':0}, 'TRACKERS':{}}
    monkeypatch.setattr('src.uploadscreens.screenshots_dir', lambda *_a: tmp_path)
    monkeypatch.setattr('src.uploadscreens.manifest_files', lambda *_a: sorted(tmp_path.glob('*.png')))
    async def upload(args):
        image, host = str(args[0]), str(args[1])
        calls.append((Path(image).name,host))
        if host == 'lostimg' and image.endswith('image-2.png'):
            return {'status':'failed','reason':'host timed out'}
        url = 'https://images.example/' + Path(image).name
        return {'status':'success','raw_url':url,'img_url':url,'web_url':url}
    async def all_done_failure_first(tasks, **_kwargs):
        await asyncio.gather(*tasks)
        return sorted(tasks, key=lambda t: t.result() is not None), set()
    monkeypatch.setattr('src.uploadscreens.upload_image_task', upload)
    monkeypatch.setattr('src.uploadscreens.asyncio.wait', all_done_failure_first)
    def fresh():
        return Meta(base_dir=str(tmp_path), uuid='release', imghost='lostimg', image_list=[])
    images, count = asyncio.run(_upload_screens(config,fresh(),3,1,0,3,[],{},max_retries=0))
    assert count == len(images) == 3
    assert len([host for _,host in calls if host == 'lostimg']) == 3
    assert len([host for _,host in calls if host == 'ptscreens']) == 1
    # A second process reuses both retained host successes; only the failed
    # primary-host image needs a network attempt before cached fallback.
    calls.clear()
    images, count = asyncio.run(_upload_screens(config,fresh(),3,1,0,3,[],{},max_retries=0))
    assert count == len(images) == 3
    assert calls == [('image-2.png','lostimg')]
