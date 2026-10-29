import copy
import time

import pytest
from flask import Flask

from src.migration_planner import plan
from web_ui.services.migration_api import create_blueprint, example_snapshot

NOW = 100000
HASH = 'a' * 40


def verification(infohash=HASH):
    return {'destination_id':'Grape','infohash':infohash,'complete':True,'seed_ready':True,'verified_at':NOW}


def candidate(**kw):
    return {'label':'synthetic','infohash':HASH,'size_bytes':1000,'origin_kind':'ua-original','state':'matched','source_identity_matches':True,
            'age_gate_passed':True,'lifecycle_gate_passed':True,'tracker_hardlinks_remaining':0,
            'tree':{'kind':'file','complete':True,'observed_at':NOW,'entries':[{'kind':'regular','nlink':1}]},
            'own_destination':verification(),'related_handoffs':[verification('b'*40)],'related_handoffs_complete':True,**kw}


def snapshot(*rows):
    return {'version':1,'source':'synthetic-import','observed_at':NOW,
            'destination':{'id':'Grape','role':'grape','capacity_bytes':10000,'used_bytes':5000,'pending_bytes':1000,'headroom_bytes':1000,'observed_at':NOW,'estimated_bytes_per_second':100},
            'candidates':list(rows)}


def test_evidence_complete_is_never_authorization_and_exact_hash_required():
    result = plan(snapshot(candidate()),now=NOW)
    assert result['candidates'][0]['evidence_complete']
    assert not result['execution_authorized'] and not result['candidates'][0]['execution_authorized']
    assert result['additional_transfer_bytes'] == 1000 and result['estimated_transfer_seconds'] == 10
    assert result['available_after_reservations_bytes'] == 3000
    wrong = candidate(own_destination=verification('c'*40))
    row = plan(snapshot(wrong),now=NOW)['candidates'][0]
    assert not row['evidence_complete'] and not row['own_exact_torrent_verified']
    assert any('own exact infohash' in b for b in row['blockers'])


@pytest.mark.parametrize('change,reason',[
    (lambda c:c.update(state='unknown'),'handoff state'),
    (lambda c:c.update(source_identity_matches=None),'source identity'),
    (lambda c:c.update(origin_kind='historical',state='recovery-required'),'explicit recovery'),
    (lambda c:c.update(own_destination=None),'own exact infohash'),
    (lambda c:c['own_destination'].update(seed_ready=False),'seed-ready'),
    (lambda c:c['own_destination'].update(destination_id='Other'),'Grape'),
    (lambda c:c.update(related_handoffs=None),'related tracker'),
    (lambda c:c.update(related_handoffs_complete=None),'enumerated'),
    (lambda c:c['related_handoffs'][0].update(complete=False),'related tracker'),
    (lambda c:c['related_handoffs'][0].update(verified_at=NOW-3601),'related tracker'),
    (lambda c:c.update(tracker_hardlinks_remaining=1),'Tracker hardlinks'),
    (lambda c:c['tree']['entries'][0].update(nlink=2),'nlink == 1'),
    (lambda c:c['tree']['entries'][0].update(nlink=None),'nlink == 1'),
    (lambda c:c['tree'].update(kind='directory',entries=[{'kind':'symlink','nlink':1}]),'symlinks'),
    (lambda c:c['tree'].update(kind='directory',entries=[{'kind':'other'}]),'unusual'),
    (lambda c:c['tree'].update(complete=False),'inode/tree'),
    (lambda c:c['tree'].update(observed_at=NOW-3601),'inode/tree'),
    (lambda c:c.update(age_gate_passed=False),'age gate'),
    (lambda c:c.update(lifecycle_gate_passed=None),'lifecycle gate'),
])
def test_partial_stale_hardlink_and_unusual_tree_blockers(change,reason):
    row=candidate();change(row)
    result=plan(snapshot(row),now=NOW)['candidates'][0]
    assert not result['evidence_complete']
    assert any(reason in b for b in result['blockers'])


def test_direct_beyondhd_keeps_own_hash_and_links_checks_retained_tag_not_required():
    row=candidate(origin_kind='direct-beyondhd',lifecycle_gate_passed=None)
    assert plan(snapshot(row),now=NOW)['candidates'][0]['evidence_complete']
    row['tracker_hardlinks_remaining']=2
    assert not plan(snapshot(row),now=NOW)['candidates'][0]['evidence_complete']
    row['tracker_hardlinks_remaining']=0;row['own_destination']=verification('c'*40)
    assert not plan(snapshot(row),now=NOW)['candidates'][0]['evidence_complete']


def test_capacity_reservations_stale_and_unknown():
    data=snapshot(candidate(size_bytes=4000))
    result=plan(data,now=NOW)
    assert result['shortage_bytes']==1000 and not result['candidates'][0]['evidence_complete']
    data['destination']['capacity_bytes']=None
    assert plan(data,now=NOW)['shortage_bytes'] is None
    data=snapshot(candidate());data['observed_at']=NOW-3601
    assert not plan(data,now=NOW)['candidates'][0]['evidence_complete']
    data['observed_at']=NOW;data['destination']['observed_at']=None
    assert not plan(data,now=NOW)['candidates'][0]['evidence_complete']


def test_duplicates_reliable_content_identity_and_unverified_reuse():
    a=candidate();b=candidate(infohash='d'*40,own_destination=verification('d'*40))
    result=plan(snapshot(a,b,copy.deepcopy(a)),now=NOW)
    assert result['additional_transfer_bytes']==2000 and result['duplicate_candidates_ignored']==1
    assert result['unique_payloads']==2  # same name/size never proves identity
    a['payload_sha256']=b['payload_sha256']='f'*64
    result=plan(snapshot(a,b),now=NOW)
    assert result['additional_transfer_bytes']==1000 and result['unique_payloads']==1
    a['reuse']={'destination_id':'Grape','payload_sha256':'f'*64,'size_bytes':1000,'verified':True,'verified_at':NOW}
    result=plan(snapshot(a,b),now=NOW)
    assert result['additional_transfer_bytes']==0 and result['verified_snapshot_reuse_bytes']==1000
    a['reuse']['destination_id']='Other'
    result=plan(snapshot(a),now=NOW)
    assert result['additional_transfer_bytes']==1000 and result['candidates'][0]['reuse']=='candidate-only-unverified'
    a['reuse']['destination_id']='Grape';a['reuse']['verified_at']=NOW-3601
    assert plan(snapshot(a),now=NOW)['additional_transfer_bytes']==1000
    conflicting=copy.deepcopy(a);conflicting['size_bytes']=2000
    result=plan(snapshot(a,conflicting),now=NOW)
    assert result['additional_transfer_bytes']==2000 and not result['candidates'][0]['evidence_complete']


@pytest.mark.parametrize('change',[
    lambda s:s.update(version=True),
    lambda s:s.update(password='forbidden'),
    lambda s:s.update(path='/server/secret'),
    lambda s:s.update(candidates=[candidate()]*501),
    lambda s:s['destination'].update(role='not-grape'),
    lambda s:s['destination'].update(capacity_bytes=-1),
    lambda s:s['destination'].update(pending_bytes=True),
    lambda s:s['destination'].update(used_bytes=10001),
    lambda s:s['destination'].update(estimated_bytes_per_second=0),
    lambda s:s['candidates'][0].update(infohash='same-name-not-hash'),
    lambda s:s['candidates'][0].update(source_identity_matches=1),
    lambda s:s['candidates'][0]['tree'].update(entries=[{'kind':'regular','nlink':-1}]),
    lambda s:s.update(observed_at=float('nan')),
])
def test_invalid_or_sensitive_snapshot_rejected(change):
    data=snapshot(candidate());change(data)
    with pytest.raises(ValueError):plan(data,now=NOW)


def test_api_auth_bounded_import_and_no_action_endpoints():
    state={'auth':True,'csrf':True,'origin':True}
    app=Flask(__name__,template_folder='../web_ui/templates')
    app.register_blueprint(create_blueprint(authenticated=lambda:state['auth'],csrf_valid=lambda:state['csrf'],same_origin=lambda:state['origin'],csrf_token=lambda:'dummy'))
    client=app.test_client()
    example=client.get('/api/migration-planner/example').json
    response=client.post('/api/migration-planner/preview',json=example)
    assert response.status_code==200 and not response.json['candidates'][0]['evidence_complete']
    assert not response.json['execution_authorized']
    assert client.post('/api/migration-planner/preview',json={'path':'/tmp/file'}).status_code==400
    assert client.post('/api/migration-planner/preview',data='x'*2100000,content_type='application/json').status_code==413
    for field,status in [('auth',401),('csrf',403),('origin',403)]:
        state[field]=False
        assert client.post('/api/migration-planner/preview',json=example).status_code==status
        state[field]=True
    assert client.get('/migration-planner').status_code==200
    assert all(not any(word in str(rule) for word in ('execute','transfer','delete','ssh')) for rule in app.url_map.iter_rules())


def test_planning_performance():
    rows=[candidate(infohash=f'{i:040x}',own_destination=verification(f'{i:040x}')) for i in range(500)]
    start=time.perf_counter();result=plan(snapshot(*rows),now=NOW);elapsed=time.perf_counter()-start
    print(f'500-candidate snapshot plan: {elapsed:.4f}s')
    assert len(result['candidates'])==500 and elapsed<10
