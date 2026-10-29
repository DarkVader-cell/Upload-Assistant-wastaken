import asyncio
import os
import subprocess
import sys
import time

import numpy as np
import pytest
from flask import Flask
from PIL import Image

from src.screenshot_intelligence import MAX_BYTES, ImageAnalyzer
from src.screenshot_manifest import register
from src.screenshot_review import ReviewedScreenshot, list_review_items, refill_screenshot_slot, target_count
from web_ui.services.screenshot_intelligence_api import create_blueprint


def images(tmp_path):
    black = tmp_path / 'black.png'; Image.new('RGB', (320, 180)).save(black)
    flat = tmp_path / 'flat.png'; Image.new('RGB', (320, 180), 'gray').save(flat)
    detail = tmp_path / 'detail.png'; Image.fromarray(np.random.default_rng(1).integers(0, 256, (108, 192, 3), dtype=np.uint8)).save(detail)
    return [ReviewedScreenshot(str(i), p, i) for i, p in enumerate([black, flat, detail, detail])]


def test_new_services_import_without_user_configuration(tmp_path):
    result = subprocess.run([sys.executable, '-c', 'import src.screenshot_intelligence; import web_ui.services.workflow_tools'],
        env={**os.environ, 'UA_DATA_DIR':str(tmp_path)}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path/'data'/'config.py').exists()


def test_black_detail_duplicates_remote_group_and_cache(tmp_path):
    items = images(tmp_path)
    items += [ReviewedScreenshot('remote', None, 4, 'remote', {'raw_url':'http://127.0.0.1/never-fetch'}), ReviewedScreenshot('group', items[2].path, 5, group='FILE_1')]
    analyzer = ImageAnalyzer()
    result = analyzer.review(items, tmp_path)
    rows = result['images']
    assert 'near-black' in rows[0]['reasons']
    assert 'low-detail-or-blur-proxy' in rows[1]['reasons']
    assert rows[2]['reasons'] == []
    assert rows[3]['duplicate_of'] == ['2']
    assert rows[4]['status'] == 'unknown' and rows[4]['reasons'] == ['remote-image-not-fetched']
    assert not rows[5]['duplicate_of']
    assert analyzer.decodes == 3
    analyzer.review(items, tmp_path)
    assert analyzer.decodes == 3
    Image.new('RGB', (320, 180), 'white').save(items[0].path)
    analyzer.review(items, tmp_path)
    assert analyzer.decodes == 4
    assert all(r['text_or_credits'] == 'unknown' for r in rows)


def test_confinement_limits_cancellation_and_budget(tmp_path):
    root = tmp_path / 'allowed'; root.mkdir()
    items = images(tmp_path)
    analyzer = ImageAnalyzer(cache_size=1)
    with pytest.raises(ValueError): analyzer.inspect(items[0].path, root)
    link = root / 'escape.png'; link.symlink_to(items[0].path)
    with pytest.raises(ValueError): analyzer.inspect(link, root)
    large = root / 'large.png'
    with large.open('wb') as stream: stream.truncate(MAX_BYTES + 1)
    with pytest.raises(ValueError): analyzer.inspect(large, root)
    dimensions = root / 'huge.png'; Image.new('1', (4001, 4001)).save(dimensions)
    with pytest.raises(ValueError): analyzer.inspect(dimensions, root)
    with pytest.raises(InterruptedError): analyzer.review(items, tmp_path, cancelled=lambda: True)
    assert analyzer.review(items, tmp_path, budget_seconds=-1)['images'][0]['status'] == 'unknown'
    assert analyzer.review(items * 26, tmp_path)['truncated']
    assert len(analyzer._cache) == 1


def test_api_decisions_bound_to_image_version_and_auth(tmp_path):
    root = tmp_path / 'tmp' / 'release'; (root / 'screenshots').mkdir(parents=True)
    paths = [i.path for i in images(root / 'screenshots')[:3]]
    paths = register(tmp_path, 'release', paths, 'main')
    state = {'auth': True, 'csrf': True, 'origin': True}
    app = Flask(__name__, template_folder='../web_ui/templates')
    app.register_blueprint(create_blueprint(resolve_review=lambda s: (root, {}) if s == 'dummy' else None,
        authenticated=lambda: state['auth'], csrf_valid=lambda: state['csrf'], same_origin=lambda: state['origin'], csrf_token=lambda: 'dummy'))
    client = app.test_client(); query = '?session_id=dummy'
    rows = client.get('/api/screenshot-intelligence' + query).json['images']
    assert len(rows) == 3
    payload = {'id':rows[0]['id'], 'version':rows[0]['version'], 'decision':'accepted'}
    assert client.post('/api/screenshot-intelligence/decision' + query, json=payload).status_code == 200
    assert client.get('/api/screenshot-intelligence' + query).json['images'][0]['decision'] == 'accepted'
    assert client.get('/api/screenshot-intelligence/' + rows[0]['id'] + '/thumbnail' + query).mimetype == 'image/jpeg'
    assert client.get('/api/screenshot-intelligence/unknown/thumbnail' + query).status_code == 404
    Image.new('RGB', (320,180), 'blue').save(paths[0])
    assert client.get('/api/screenshot-intelligence' + query).json['images'][0]['decision'] == 'unreviewed'
    assert client.post('/api/screenshot-intelligence/decision' + query, json=payload).status_code == 409
    for field, status in [('csrf',403), ('origin',403), ('auth',401)]:
        state[field] = False
        assert client.post('/api/screenshot-intelligence/decision' + query, json=payload).status_code == status
        state[field] = True
    assert client.get('/api/screenshot-intelligence?session_id=unknown').status_code == 404
    assert client.get('/screenshot-intelligence').status_code == 200


def test_single_rejected_refill_preserves_accepted_slots_order_and_target(tmp_path, monkeypatch):
    root = tmp_path / 'tmp' / 'release'; (root / 'screenshots').mkdir(parents=True)
    paths = [i.path for i in images(root / 'screenshots')[:3]]
    paths = register(tmp_path, 'release', paths, 'main')
    before = list_review_items(root, {})
    accepted = [p.read_bytes() for p in [paths[0], paths[2]]]
    async def capture(_root, _meta, target):
        Image.new('RGB', (320,180), 'red').save(target.path)
        return 3.0
    monkeypatch.setattr('src.screenshot_review._capture_fresh_frame', capture)
    replaced = asyncio.run(refill_screenshot_slot(root, {}, before[1].id))
    after = list_review_items(root, {})
    assert [i.id for i in before] == [i.id for i in after]
    assert replaced.id == before[1].id and target_count(root, 3) == 3
    assert [paths[0].read_bytes(), paths[2].read_bytes()] == accepted


def test_image_scoring_performance(tmp_path):
    items = images(tmp_path)
    analyzer = ImageAnalyzer()
    start = time.perf_counter(); analyzer.review(items, tmp_path); cold = time.perf_counter() - start
    start = time.perf_counter(); analyzer.review(items, tmp_path); warm = time.perf_counter() - start
    print(f'image scoring 3 unique small synthetic images: cold={cold:.4f}s warm={warm:.4f}s decodes={analyzer.decodes}')
    assert cold < 10 and analyzer.decodes == 3
