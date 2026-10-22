"""Synthetic history only: no tracker submissions or real retry processes."""
# ruff: noqa: S101
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

from src.upload_library import filter_releases, releases
from web_ui.upload_library import create_blueprint


def record(id_, success=(), failed=(), path='/media/test.mkv'):
    return {'id': id_, 'source_path': path, 'release_name': '<Film>', 'status': 'completed', 'trackers': ['A', 'B'], 'successful_trackers': list(success), 'failed_trackers': list(failed), 'category': 'MOVIE', 'resolution': '2160p'}


def test_aggregates_success_across_attempts_without_reuploading():
    store=SimpleNamespace(max_entries=500, search=Mock(return_value=[record('new',['B']),record('old',['A'],['B'])]))
    rows=releases(store)
    assert len(rows)==1
    assert rows[0]['successful_trackers']==['A','B']
    assert rows[0]['failed_trackers']==[]
    assert rows[0]['attempts']==2
    assert filter_releases(rows,trackers=['A','B'],mode='missing')==[]


@pytest.mark.parametrize('mode, targets, expected', [('missing',['A'],0),('missing',['B'],1),('uploaded',['A'],1),('failed',['B'],1),('unattempted',['C'],1),('unattempted',['B'],0)])
def test_exact_tracker_filters(mode,targets,expected):
    rows=[record('x',['A'],['B'])]
    assert len(filter_releases(rows,trackers=targets,mode=mode))==expected


@pytest.fixture
def context(tmp_path):
    store=SimpleNamespace(max_entries=500, search=Mock(return_value=[record('old',['A'],['B'])]),record_release=Mock())
    flags={'auth':True,'csrf':True,'origin':True}
    validate=Mock(side_effect=lambda p:p)
    app=Flask(__name__)
    app.register_blueprint(create_blueprint(store=lambda:store,trackers=lambda:{'A','B','C'},validate_path=validate,metadata_root=tmp_path,authenticated=lambda:flags['auth'],csrf_valid=lambda:flags['csrf'],same_origin=lambda:flags['origin'],csrf_token=lambda:'dummy'))
    return app.test_client(),store,flags,validate


def test_retry_plan_excludes_success_and_rejects_unknown_ids(context):
    client,_,_,_=context
    row=client.get('/api/upload-library').get_json()['rows'][0]
    result=client.post('/api/upload-library/retry-plan',json={'ids':[row['id']],'trackers':['A','B']}).get_json()
    assert result['plans'][0]['trackers']==['B']
    assert client.post('/api/upload-library/retry-plan',json={'ids':['bad'],'trackers':['B']}).status_code==400
    assert client.post('/api/upload-library/retry-plan',json={'ids':[row['id']],'trackers':['B;echo']}).status_code==400
    already=client.post('/api/upload-library/retry-plan',json={'ids':[row['id']],'trackers':['A']}).get_json()
    assert already['plans']==[]
    assert len(already['skipped'])==1


def test_retry_missing_path_is_skipped(context):
    client,_,_,validate=context
    row=client.get('/api/upload-library').get_json()['rows'][0]
    validate.side_effect=ValueError('missing')
    response=client.post('/api/upload-library/retry-plan',json={'ids':[row['id']],'trackers':['B']}).get_json()
    assert response['plans']==[]
    assert len(response['skipped'])==1


def test_security_and_bad_filters(context):
    client,_,flags,_=context
    assert client.get('/api/upload-library?tracker=A&mode=missing').get_json()['total']==0
    assert client.get('/api/upload-library?tracker=B&mode=failed').get_json()['total']==1
    assert client.get('/api/upload-library?offset=notanumber').status_code==400
    flags['auth']=False
    assert client.get('/api/upload-library').status_code==401
    flags['auth']=True
    flags['csrf']=False
    assert client.post('/api/upload-library/import',json={}).status_code==403
    flags['csrf']=True
    flags['origin']=False
    assert client.post('/api/upload-library/retry-plan',json={}).status_code==403
