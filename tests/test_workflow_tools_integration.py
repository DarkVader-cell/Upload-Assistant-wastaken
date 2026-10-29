"""Reachable real-server flows, isolated app state and mocked capture; no execution."""
import json
from unittest.mock import Mock

from PIL import Image

from src.screenshot_manifest import register
from web_ui import server
from web_ui.browse_index import BrowseIndex


def test_new_subscription_preserves_live_completion_when_pump_already_finished():
    state=server._make_process_state('synthetic.mkv','')
    server._init_session_events(state,label='Synthetic',keep_running=True,prompt_timeout=0)
    server._publish_session_event(state,{'type':'prompt_sound'})
    server._publish_session_event(state,{'type':'exit','code':0})
    server._finish_session(state,0)
    live=[json.loads(chunk.removeprefix('data: ')) for chunk in server._stream_session_events('dummy',state,0,replay=False)]
    assert [e['type'] for e in live]==['replay_done','prompt_sound','exit','finished']
    resumed=[json.loads(chunk.removeprefix('data: ')) for chunk in server._stream_session_events('dummy',state,0)]
    assert [e['type'] for e in resumed]==['prompt_sound','exit','replay_done','finished']
    assert live[-2]['code']==0 and state['clients']==0


def test_observation_adapter_reads_index_without_scanning(tmp_path, monkeypatch):
    root=tmp_path/'media';root.mkdir();source=root/'movie.mkv';source.touch()
    index=BrowseIndex(tmp_path/'browse.sqlite3')
    index.record_observations([str(root)],[{'path':str(source),'type':'file'},{'path':str(tmp_path/'private'),'type':'file'}])
    monkeypatch.setattr(index,'_refresh',Mock(side_effect=AssertionError('must not scan')))
    rows=index.recorded_candidates([str(root)])
    assert len(rows)==1 and rows[0]['source_path']==str(source) and rows[0]['updated_at']>0
    assert index.recorded_candidates([str(tmp_path/'other')])==[]


def test_reachable_browse_discovery_reviewed_queue_rules_and_planner(tmp_path,monkeypatch):
    root=tmp_path/'media';root.mkdir();source=root/'synthetic.mkv';source.touch()
    for name in ('_is_authenticated','_webui_auth_ok','_verify_csrf_header','_verify_same_origin'):
        monkeypatch.setattr(server,name,lambda:True)
    monkeypatch.setattr(server,'_get_browse_roots',lambda:[str(root)])
    monkeypatch.setattr(server,'_library_config',lambda:{'TRACKERS':{'A':{'api_key':'NEVER-EXPORT-SECRET'},'DEFAULT':{}},'TORRENT_CLIENTS':{'local':{'password':'NEVER-EXPORT-SECRET'}}})
    monkeypatch.setattr(server,'_load_argument_presets',lambda:[{'name':'Movie','arguments':'--screens 6'}])
    launch=Mock(side_effect=AssertionError('no execution authorized'))
    monkeypatch.setattr(server.subprocess,'Popen',launch)
    with server.app.test_client() as client:
        for url in ('/discovery','/automation-rules','/migration-planner','/screenshot-intelligence'):
            response=client.get(url)
            assert response.status_code==200 and b'workflow_tools.css' in response.data
        browsed=client.get('/api/browse',query_string={'path':str(root)})
        assert browsed.status_code==200
        assert client.post('/api/discovery/refresh',json={}).status_code==200
        listing=client.get('/api/discovery',query_string={'q':'synthetic','tracker':'A'}).json
        assert len(listing['rows'])==1 and listing['rows'][0]['codec'] is None
        candidate=listing['rows'][0]
        preview=client.post('/api/discovery/preview',json={'ids':[candidate['id']],'trackers':['A']}).json
        assert preview['plans'][0]['path']==str(source)
        saved=client.post('/api/save_queue',json={'items':[{'path':str(source),'args':'-tk A'}]}).json
        assert saved['queued']
        reviewed=client.get('/api/workflow-tools/review-queue',query_string={'path':saved['path']})
        assert reviewed.status_code==200 and reviewed.json['items']==[{'path':str(source),'args':'-tk A'}]
        for invalid in (str(source), '\x00', 'x'*4097):
            assert client.get('/api/workflow-tools/review-queue',query_string={'path':invalid}).status_code==400
        settings=client.get('/api/automation-rules').json
        assert settings['references']=={'suggest_trackers':['A'],'preset':['Movie'],'client_profile':['local']}
        assert 'NEVER-EXPORT-SECRET' not in json.dumps(settings)
        result=client.post('/api/automation-rules/preview',json={'id':candidate['id']})
        assert result.status_code==200 and result.json['requires_confirmation']
        snapshot=client.get('/api/migration-planner/example').json
        planned=client.post('/api/migration-planner/preview',json=snapshot)
        assert planned.status_code==200 and not planned.json['execution_authorized']
    launch.assert_not_called()


def test_registered_screenshot_analysis_and_slot_refill_preserve_others(tmp_path,monkeypatch):
    root=tmp_path/'tmp'/'session';(root/'screenshots').mkdir(parents=True)
    paths=[]
    for number,color in enumerate(('blue','black','red')):
        path=root/'screenshots'/f'{number}.png';Image.new('RGB',(320,180),color).save(path);paths.append(path)
    paths=register(tmp_path,'session',paths,'main')
    for name in ('_is_authenticated','_webui_auth_ok','_verify_csrf_header','_verify_same_origin'):
        monkeypatch.setattr(server,name,lambda:True)
    monkeypatch.setattr(server,'_resolve_execution_screenshot_review',lambda s:(root,{'category':'MOVIE'}) if s=='dummy' else None)
    async def capture(_root,_meta,target):
        Image.new('RGB',(320,180),'green').save(target.path);return 2.0
    monkeypatch.setattr('src.screenshot_review._capture_fresh_frame',capture)
    before=[p.read_bytes() for p in paths]
    with server.app.test_client() as client:
        rows=client.get('/api/screenshot-intelligence?session_id=dummy').json['images']
        assert rows[1]['reasons'][0]=='near-black'
        assert client.post('/api/screenshot-intelligence/decision?session_id=dummy',json={'id':rows[0]['id'],'version':rows[0]['version'],'decision':'accepted'}).status_code==200
        listing=client.get('/api/execution_screenshots?session_id=dummy').json
        assert all(i['can_refill'] for i in listing['screenshots'])
        response=client.post('/api/execution_screenshots/'+rows[1]['id']+'/refill',json={'session_id':'dummy'})
        assert response.status_code==200
        after=client.get('/api/screenshot-intelligence?session_id=dummy').json['images']
        assert after[0]['decision']=='accepted' and [i['id'] for i in rows]==[i['id'] for i in after]
    assert paths[0].read_bytes()==before[0] and paths[2].read_bytes()==before[2] and paths[1].read_bytes()!=before[1]
