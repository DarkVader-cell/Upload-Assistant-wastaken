import copy
import time

import pytest
from flask import Flask

from src.automation_rules import RuleStore, evaluate, validate_schema
from web_ui.services.rules_api import create_blueprint

REFS = {'suggest_trackers':['A','B'], 'preset':['default','archive'], 'client_profile':['local']}
ID = 'a' * 64


def rule(name='Movie', priority=1, **kw):
    return {'name':name,'priority':priority,'enabled':True,'match':'all','conditions':[{'field':'category','operator':'equals','value':'MOVIE'}], 'actions':{'suggest_trackers':['A'],'preset':'default'}, **kw}


def schema(*rules): return {'version':1, 'rules':list(rules), 'overrides':{}}


def test_match_missing_metadata_case_and_deterministic_conflicts():
    doc = validate_schema(schema(rule('Z',1),rule('A',2, actions={'preset':'archive','suggest_trackers':['B']})), REFS)
    candidate = {'id':ID, 'category':'movie'}
    result = evaluate(doc,candidate)
    assert result['proposals']['preset'] == 'archive'
    assert result['proposals']['suggest_trackers'] == ['A','B']
    assert result['conflicts'][0]['ignored'] == 'default'
    assert result['proposals']['requirements'] == ['screenshot-review','torrent-verification']
    assert result['requires_confirmation']
    assert evaluate({**doc,'rules':list(reversed(doc['rules']))}, candidate) == result
    missing = evaluate(doc,{'id':ID})
    assert not any(r['matched'] for r in missing['rules'])
    assert missing['rules'][0]['conditions'][0]['provenance'] == 'unknown'
    doc['overrides'][ID] = {'preset':'default','requirements':['metadata-review']}
    result = evaluate(doc,candidate)
    assert result['proposals']['preset'] == 'default'
    assert 'explicit-per-release-override' in result['provenance']['preset']
    assert result['proposals']['requirements'] == ['metadata-review','screenshot-review','torrent-verification']


def test_and_or_literal_operators_and_disabled():
    conditions = [{'field':'resolution','operator':'in','value':['1080P','2160p']},{'field':'edition','operator':'contains','value':'.*'}]
    doc = validate_schema(schema(rule(conditions=conditions,match='any')),REFS)
    assert evaluate(doc,{'id':ID,'resolution':'1080p'})['rules'][0]['matched']
    assert not evaluate(doc,{'id':ID,'edition':'Directors Cut'})['rules'][0]['matched']
    doc['rules'][0]['match'] = 'all'
    assert not evaluate(doc,{'id':ID,'resolution':'1080p'})['rules'][0]['matched']
    doc['rules'][0]['enabled'] = False
    assert not evaluate(doc,{'id':ID,'resolution':'1080p','edition':'.*'})['rules'][0]['matched']


@pytest.mark.parametrize('change',[
    lambda d: d.update(version=True),
    lambda d: d.update(secret='password'),
    lambda d: d['rules'][0].update(actions={'shell':'rm -rf /'}),
    lambda d: d['rules'][0].update(actions={'auto_submit':True}),
    lambda d: d['rules'][0].update(actions={'requirements':[]}),
    lambda d: d['rules'][0].update(actions={'preset':'--unattended'}),
    lambda d: d['rules'][0].update(actions={'client_profile':'missing'}),
    lambda d: d['rules'][0].update(actions={'suggest_trackers':['UNKNOWN']}),
    lambda d: d['rules'][0]['conditions'][0].update(operator='regex'),
    lambda d: d['rules'][0]['conditions'][0].update(field='password'),
    lambda d: d['rules'][0]['conditions'][0].update(value=True),
    lambda d: d['rules'][0].update(priority=True),
    lambda d: d['rules'][0].update(enabled='false'),
    lambda d: d['rules'][0].update(conditions=[]),
    lambda d: d.update(rules=[rule()] * 33),
    lambda d: d['rules'].append(rule('movie')),
    lambda d: d.update(overrides={'/arbitrary/path':{'preset':'default'}}),
    lambda d: d['rules'][0].update(name='x'*300000),
])
def test_malicious_and_oversized_schemas(change):
    doc = schema(rule()); change(doc)
    with pytest.raises(ValueError): validate_schema(doc, REFS)


def test_persistence_revision_no_legacy_config_mutation(tmp_path):
    path = tmp_path/'rules.json'; store = RuleStore(path)
    legacy = tmp_path/'config.py'; legacy.write_text('unchanged')
    empty, revision = store.load(REFS)
    assert empty == schema()
    clean, next_revision = store.save(schema(rule()),revision,REFS)
    assert RuleStore(path).load(REFS) == (clean,next_revision)
    with pytest.raises(FileExistsError): store.save(schema(),revision,REFS)
    assert legacy.read_text() == 'unchanged'
    invalid = copy.deepcopy(clean); invalid['rules'][0]['actions'] = {'execute':True}
    with pytest.raises(ValueError): store.save(invalid,next_revision,REFS)
    assert RuleStore(path).load(REFS)[0] == clean
    assert not list(tmp_path.glob('.automation-rules-*'))


def test_api_auth_preview_import_export_and_override(tmp_path):
    state = {'auth':True,'csrf':True,'origin':True}
    app = Flask(__name__,template_folder='../web_ui/templates')
    app.register_blueprint(create_blueprint(store=RuleStore(tmp_path/'rules.json'), references=lambda:REFS,
        candidates=lambda:[{'id':ID,'release_name':'synthetic','category':'MOVIE'}], authenticated=lambda:state['auth'],
        csrf_valid=lambda:state['csrf'], same_origin=lambda:state['origin'], csrf_token=lambda:'dummy'))
    client = app.test_client()
    data = client.get('/api/automation-rules').json
    doc = schema(rule()); doc['overrides'][ID] = {'client_profile':'local'}
    payload = {'schema':doc,'revision':data['revision']}
    assert client.post('/api/automation-rules',json=payload).status_code == 200
    assert client.post('/api/automation-rules',json=payload).status_code == 409
    assert client.get('/api/automation-rules').json['schema'] == doc
    result = client.post('/api/automation-rules/preview',json={'id':ID}).json
    assert result['proposals']['client_profile'] == 'local' and result['requires_confirmation']
    assert client.post('/api/automation-rules/preview',json={'id':'unknown'}).status_code == 400
    assert client.post('/api/automation-rules/preview',json={'id':ID,'schema':schema(rule(actions={'delete':True}))}).status_code == 400
    assert client.post('/api/automation-rules',data='x'*270000,content_type='application/json').status_code == 413
    for field, status in [('auth',401),('csrf',403),('origin',403)]:
        state[field]=False
        assert client.post('/api/automation-rules',json=payload).status_code == status
        state[field]=True
    assert client.get('/automation-rules').status_code == 200
    assert client.get('/api/automation-rules/candidates').json['candidates'][0]['id'] == ID


def test_rule_performance():
    doc = validate_schema(schema(*(rule(str(i)) for i in range(32))),REFS)
    start = time.perf_counter()
    for _ in range(1000): evaluate(doc, {'id':ID,'category':'MOVIE'})
    elapsed = time.perf_counter()-start
    print(f'1000 candidates x 32 rules: {elapsed:.4f}s')
    assert elapsed < 10
