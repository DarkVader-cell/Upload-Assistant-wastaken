"""Only generated images and fake host responses; no tracker uploads."""
# ruff: noqa: S101
from src.runtime.image_progress import ImageUploadJournal


def test_persisted_success_survives_process_restart_but_not_changed_image(tmp_path):
    image=tmp_path/'frame.png'
    image.write_bytes(b'first')
    store=ImageUploadJournal(tmp_path)
    key=store.key(str(image),'host')
    result={'status':'success','raw_url':'https://img.example/full.png','img_url':'https://img.example/thumb.png','web_url':'https://img.example/page','delete_token':'NEVER_STORE'}
    store.put(key,result)
    loaded=ImageUploadJournal(tmp_path).get(key)
    assert loaded and loaded['raw_url']==result['raw_url']
    assert 'NEVER_STORE' not in store.path.read_text()
    image.write_bytes(b'changed')
    assert store.get(store.key(str(image),'host')) is None
    assert store.key(str(image),'otherhost')!=key


def test_failed_or_unsafe_results_are_not_reused(tmp_path):
    store=ImageUploadJournal(tmp_path)
    store.put('key',{'status':'failed'})
    assert store.get('key') is None
    store.put('key',{'status':'success','raw_url':'javascript:bad','img_url':'https://img.example/a','web_url':'https://img.example/b'})
    assert store.get('key') is None
