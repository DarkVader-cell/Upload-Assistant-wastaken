"""Upload Library routes. Retry plans feed the existing WebUI execution queue."""
import hashlib
import json
from pathlib import Path

from flask import Blueprint, jsonify, redirect, request

from src.upload_library import filter_releases, releases


def create_blueprint(*, store, trackers, validate_path, metadata_root, authenticated, csrf_valid, same_origin, csrf_token):
    del csrf_token  # Native workspace uses the main application's CSRF token.
    bp = Blueprint('upload_library', __name__)

    @bp.before_request
    def protect():
        if not authenticated():
            return jsonify(error='Authentication required'), 401
        if request.method == 'POST' and (not csrf_valid() or not same_origin()):
            return jsonify(error='Invalid CSRF or origin'), 403
        return None

    @bp.get('/upload-library')
    def page():
        return redirect('/?workspace=library')

    @bp.get('/api/upload-library')
    def listing():
        try:
            names = sorted(trackers())
            selected = request.args.getlist('tracker')
            if set(selected) - set(names):
                raise ValueError('Unknown tracker')
            rows = filter_releases(releases(store()), query=request.args.get('q', ''), trackers=selected, mode=request.args.get('mode', 'missing'), category=request.args.get('category', ''), resolution=request.args.get('resolution', ''), errors=request.args.get('errors') == '1')
            offset = max(0, int(request.args.get('offset', 0)))
            limit = min(200, max(1, int(request.args.get('limit', 100))))
            return jsonify(rows=rows[offset:offset+limit], total=len(rows), trackers=names, offset=offset, limit=limit)
        except (ValueError, TypeError):
            return jsonify(error='Invalid filters'), 400

    @bp.post('/api/upload-library/retry-plan')
    def retry_plan():
        try:
            data = request.get_json()
            ids, targets = data['ids'], data['trackers']
            if not isinstance(ids, list) or not 1 <= len(ids) <= 50 or any(not isinstance(i, str) for i in ids):
                raise ValueError('Select 1-50 releases')
            if not isinstance(targets, list) or not targets or any(not isinstance(t, str) for t in targets) or set(targets) - set(trackers()):
                raise ValueError('Select configured trackers')
            by_id = {r['id']: r for r in releases(store())}
            plans, skipped = [], []
            for id_ in dict.fromkeys(ids):
                row = by_id.get(id_)
                if row is None:
                    raise ValueError('Unknown release')
                pending = sorted(set(targets) - set(row['successful_trackers']))
                if not pending:
                    skipped.append({'id': id_, 'reason': 'Already recorded successful on selected trackers'})
                    continue
                try:
                    path = str(validate_path(row['source_path']))
                except Exception:
                    skipped.append({'id': id_, 'reason': 'Source missing or outside approved roots'})
                    continue
                plans.append({'id': id_, 'path': path, 'trackers': pending, 'label': row.get('release_name', '')})
            return jsonify(plans=plans, skipped=skipped)
        except (KeyError, TypeError, ValueError):
            return jsonify(error='Invalid selection or target trackers'), 400

    @bp.post('/api/upload-library/import')
    def import_metadata():
        # Only bounded, local UA metadata; never crawl arbitrary user paths.
        root = Path(metadata_root).resolve()
        count = 0
        for path in sorted(root.glob('*/meta.json'))[:5000]:
            try:
                if path.is_symlink() or not path.resolve().is_relative_to(root) or path.stat().st_size > 8 * 1024 * 1024:
                    continue
                data = json.loads(path.read_text())
                if not isinstance(data, dict) or not data.get('path'):
                    continue
                identity = hashlib.sha256((str(path) + str(path.stat().st_mtime_ns)).encode()).hexdigest()
                store().record_release(data, source='metadata-import', record_id='import-' + identity)
                count += 1
            except (OSError, ValueError, TypeError):
                continue
        return jsonify(imported=count)

    return bp
