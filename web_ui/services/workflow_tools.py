"""Thin fork integration seams, with no live client or execution calls."""
import contextlib
import shlex
import sqlite3
import time
from itertools import islice
from pathlib import Path

from flask import Blueprint, jsonify, request

from src.automation_rules import RuleStore
from src.discovery import candidates
from src.runtime.history import ReleaseHistoryStore
from web_ui.browse_index import BrowseIndex
from web_ui.services.discovery_api import create_blueprint as discovery_blueprint
from web_ui.services.migration_api import create_blueprint as migration_blueprint
from web_ui.services.rules_api import create_blueprint as rules_blueprint
from web_ui.services.screenshot_intelligence_api import create_blueprint as screenshot_blueprint

MEDIA_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.m2ts', '.ts', '.iso', '.flac', '.mp3', '.m4a', '.epub', '.pdf', '.mobi', '.azw3'}


def register_workflow_tools(app, *, state_dir, config, roots, presets, resolve_review, review_meta, validate_path, issued_queue, authenticated, csrf_valid, same_origin, csrf_token):
    """Only invoked by Web UI registration; all external access stays user-driven."""
    security = {'authenticated': authenticated, 'csrf_valid': csrf_valid, 'same_origin': same_origin, 'csrf_token': csrf_token}
    index = BrowseIndex(Path(state_dir) / 'data' / 'cache' / 'browse.sqlite3')

    def trackers():
        return sorted(set(config().get('TRACKERS', {})) - {'DEFAULT'})

    def records():
        store = ReleaseHistoryStore(state_dir, config())
        for offset in range(0, 2500, 500):
            rows = store.search(limit=500, offset=offset)
            for row in rows:
                yield {**row, 'origin': 'history'}
            if len(rows) < 500:
                break
        for row in index.recorded_candidates(roots(), 2500):
            if row['entry_type'] == 'folder' or Path(row['source_path']).suffix.casefold() in MEDIA_EXTENSIONS:
                yield row

    def candidate_rows():
        return candidates(records(), roots(), now=time.time())[0]

    def references():
        return {'suggest_trackers': trackers(), 'preset': sorted({p['name'] for p in presets()}),
                'client_profile': sorted(set(config().get('TORRENT_CLIENTS', {})) - {'default', 'DEFAULT'})}

    app.register_blueprint(discovery_blueprint(records=records, roots=roots, trackers=trackers, validate_path=validate_path, **security))
    def resolve_screenshots(session):
        resolved = resolve_review(session)
        return (resolved[0], review_meta(*resolved)) if resolved else None

    app.register_blueprint(screenshot_blueprint(resolve_review=resolve_screenshots, **security))
    app.register_blueprint(rules_blueprint(store=RuleStore(Path(state_dir) / 'data' / 'automation_rules.json'), references=references, candidates=candidate_rows, **security))
    app.register_blueprint(migration_blueprint(**security))

    @app.after_request
    def observe_browse(response):
        if request.path in ('/api/browse', '/api/browse_search') and response.status_code == 200 and authenticated():
            data = response.get_json(silent=True)
            if isinstance(data, dict) and isinstance(data.get('items'), list):
                # A disposable index must never break the existing browser.
                with contextlib.suppress(OSError, ValueError, sqlite3.Error):
                    index.record_observations(roots(), data['items'])
        return response

    bp = Blueprint('reviewed_queue', __name__)

    @bp.get('/api/workflow-tools/review-queue')
    def review_queue():
        if not authenticated():
            return jsonify(error='Authentication required'), 401
        path = request.args.get('path', '')
        if not path or not issued_queue(path):
            return jsonify(error='Only an unchanged queue issued by this running Web UI can be reviewed'), 400
        try:
            # Issuance callback verifies the content hash and confines generated files.
            lines = Path(path).read_text().splitlines()
            items = []
            for line in islice(lines, 50):
                parts = shlex.split(line)
                if not parts:
                    continue
                items.append({'path': str(validate_path(parts[0])), 'args': shlex.join(parts[1:])})
            if len(lines) > 50:
                raise ValueError('Discovery queues contain at most 50 candidates')
            return jsonify(items=items, notice='Review paths, arguments and tracker selection. This did not start execution.')
        except (OSError, ValueError):
            return jsonify(error='Queue is unavailable or a source is no longer valid'), 400

    app.register_blueprint(bp)
