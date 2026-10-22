"""Real SQLite + Flask dummy integration; never launches upload processes."""
# ruff: noqa: S101
import json
from pathlib import Path
from unittest.mock import Mock

from flask import Flask

from src.runtime.history import ReleaseHistoryStore
from web_ui.upload_library import create_blueprint


def build(tmp_path):
    store=ReleaseHistoryStore(tmp_path)
    validate=Mock(side_effect=lambda p:p)
    app=Flask(__name__,template_folder=str(Path(__file__).resolve().parents[1]/'web_ui/templates'))
    app.register_blueprint(create_blueprint(store=lambda:store,trackers=lambda:{'A','B','C'},validate_path=validate,metadata_root=tmp_path/'tmp',authenticated=lambda:True,csrf_valid=lambda:True,same_origin=lambda:True,csrf_token=lambda:'dummy'))
    return app.test_client(),store


def add(store, index, success, status='completed'):
    store.record_release({'path':f'/dummy/{index}.mkv','name':f'Dummy {index}','category':'MOVIE' if index%2==0 else 'TV','resolution':'2160p' if index%2==0 else '1080p','trackers':['A','B'],'tracker_status':{'A':{'upload_success':success},'B':{'upload_success':False}}},status=status,record_id=f'attempt-{index}')


def test_real_database_pagination_and_combined_filters(tmp_path):
    client,store=build(tmp_path)
    for i in range(205):
        add(store,i,i%2==0)
    first=client.get('/api/upload-library?limit=100').get_json()
    second=client.get('/api/upload-library?limit=100&offset=100').get_json()
    third=client.get('/api/upload-library?limit=100&offset=200').get_json()
    assert [len(p['rows']) for p in (first,second,third)]==[100,100,5]
    assert len({r['id'] for p in (first,second,third) for r in p['rows']})==205
    assert client.get('/api/upload-library?tracker=A&mode=missing').get_json()['total']==102
    assert client.get('/api/upload-library?tracker=A&mode=uploaded&category=MOVIE&resolution=2160p&errors=1').get_json()['total']==103
    assert client.get('/api/upload-library?tracker=C&mode=unattempted').get_json()['total']==205
    assert client.get('/api/upload-library?q=Dummy%20204').get_json()['total']==1


def test_import_idempotent_skips_invalid_and_renders_page(tmp_path):
    client,store=build(tmp_path)
    directory=tmp_path/'tmp'/'dummy'
    directory.mkdir(parents=True)
    (directory/'meta.json').write_text(json.dumps({'path':'/dummy/file.mkv','name':'Imported','trackers':['A'],'tracker_status':{'A':{'upload_success':True}}}))
    bad=tmp_path/'tmp'/'broken'
    bad.mkdir()
    (bad/'meta.json').write_text('not JSON')
    assert client.post('/api/upload-library/import',json={}).get_json()['imported']==1
    client.post('/api/upload-library/import',json={})
    rows=client.get('/api/upload-library').get_json()['rows']
    assert len(rows)==1 and rows[0]['attempts']==1
    assert rows[0]['successful_trackers']==['A']
    response=client.get('/upload-library')
    assert response.status_code==302
    assert response.location=='/?workspace=library'
    assert store.search()[0]['source']=='metadata-import'
