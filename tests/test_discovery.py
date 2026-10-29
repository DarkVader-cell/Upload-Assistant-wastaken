"""Synthetic projections and isolated Flask; never contacts configured services."""
import time

import pytest
from flask import Flask

from src.discovery import MAX_RECORDS, candidates, preview, select
from web_ui.services.discovery_api import create_blueprint


def record(path, **kwargs):
    return {'source_path': str(path), 'origin': 'history', 'updated_at': 1000, **kwargs}


def test_normalization_ranking_unknown_filters_and_duplicates(tmp_path):
    a = tmp_path / 'a.mkv'; a.touch()
    b = tmp_path / 'b.mkv'; b.touch()
    rows, truncated = candidates([record(a, resolution='1080p', successful_trackers=['A']), record(a, trackers=['A'], failed_trackers=['A']), record(b), record(tmp_path / 'missing', updated_at=None)], [tmp_path], now=1100)
    assert not truncated and len(rows) == 3
    result = select(list(reversed(rows)), trackers=['B'])
    assert [r['source_path'] for r in result['rows']] == [str(a), str(b), str(tmp_path / 'missing')]
    assert result['rows'][0]['failed_trackers'] == []
    assert all('unknown' in r['blockers'][0] for r in rows)
    assert select(rows, filters={'codec': 'x265'})['total'] == 0
    assert select(rows, filters={'resolution': '1080P'})['total'] == 1
    assert select(rows, trackers=['A'])['total'] == 2
    assert select(rows, trackers=['A'], mode='unattempted')['total'] == 2
    assert select(rows, limit=1, offset=1)['rows'][0]['source_path'] == str(b)
    assert select(rows, limit=1)['rows'][0]['id'] == select(list(reversed(rows)), limit=1)['rows'][0]['id']


def test_paths_ambiguous_stale_and_bounds(tmp_path):
    root = tmp_path / 'approved'; root.mkdir()
    source = root / 'movie'; source.touch()
    outside = tmp_path / 'private'; outside.touch()
    (root / 'escape').symlink_to(outside)
    inputs = [record(source, codec='x264'), record(root / '.' / 'movie', codec='x265'), record(root), record(root / 'escape'), record('relative')]
    rows, _ = candidates(inputs, [root], now=1000 + 8 * 86400)
    assert len(rows) == 1 and rows[0]['codec'] is None and not rows[0]['preparation_ready']
    assert 'Conflicting recorded codec' in rows[0]['blockers']
    assert 'Recorded evidence stale or undated' in rows[0]['blockers']
    rows2, bounded = candidates((record(source) for _ in range(MAX_RECORDS + 1)), [root], now=1100)
    assert bounded and len(rows2) == 1 and len(rows2[0]['evidence']) == MAX_RECORDS
    with pytest.raises(ValueError): select(rows, filters={'password': 'x'})
    with pytest.raises(ValueError): select(rows, offset=-1)


def test_preview_revalidates_and_never_retries_success(tmp_path):
    source = tmp_path / 'movie'; source.touch()
    rows, _ = candidates([record(source, successful_trackers=['A'])], [tmp_path], now=1100)
    calls = []
    def validate(path):
        calls.append(path)
        if not source.exists(): raise ValueError('gone')
        return path
    plan = preview(rows, [rows[0]['id']] * 2, ['A', 'B'], validate)
    assert len(plan['plans']) == 1 and plan['plans'][0]['trackers'] == ['B']
    assert calls == [str(source)] and plan['plans'][0]['requires_confirmation']
    source.unlink()
    assert not preview(rows, [rows[0]['id']], ['B'], validate)['plans']
    with pytest.raises(ValueError): preview(rows, ['missing'], ['B'], validate)


def test_api_auth_snapshot_and_invalid_inputs(tmp_path):
    source = tmp_path / 'movie'; source.touch()
    state = {'auth': False, 'csrf': True, 'origin': True, 'calls': 0}
    def records():
        state['calls'] += 1
        return [record(source)]
    app = Flask(__name__, template_folder='../web_ui/templates')
    app.register_blueprint(create_blueprint(records=records, roots=lambda: [tmp_path], trackers=lambda: ['A'], validate_path=lambda p: p,
        authenticated=lambda: state['auth'], csrf_valid=lambda: state['csrf'], same_origin=lambda: state['origin'], csrf_token=lambda: 'synthetic'))
    client = app.test_client()
    assert client.get('/api/discovery').status_code == 401
    state['auth'] = True
    for field in ('csrf', 'origin'):
        state[field] = False
        assert client.post('/api/discovery/refresh', json={}).status_code == 403
        state[field] = True
    assert client.get('/api/discovery').json['total'] == 0
    assert client.post('/api/discovery/refresh', json={}).json['total'] == 1
    for _ in range(3): assert client.get('/api/discovery?q=movie').json['total'] == 1
    assert state['calls'] == 1
    assert client.get('/api/discovery?tracker=NO').status_code == 400
    assert client.get('/api/discovery?offset=-1').status_code == 400
    assert client.post('/api/discovery/preview', json={'ids': [], 'trackers': ['A']}).status_code == 400
    assert client.get('/discovery').status_code == 200
    assert not any('execute' in str(rule) for rule in app.url_map.iter_rules())


def test_bounded_discovery_performance(tmp_path):
    source = tmp_path / 'movie'; source.touch()
    start = time.perf_counter()
    rows, _ = candidates([record(source)] * 5000, [tmp_path], now=1100)
    assert select(rows)['total'] == 1
    elapsed = time.perf_counter() - start
    print(f'discovery 5000 projections: {elapsed:.4f}s')
    assert elapsed < 10  # generous runaway guard, not a throughput claim
