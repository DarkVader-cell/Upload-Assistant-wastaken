"""Session-scoped intelligence and version-bound review decisions; no capture API."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from flask import Blueprint, Response, jsonify, render_template, request
from PIL import Image

from src.screenshot_intelligence import MAX_IMAGES, ImageAnalyzer

if TYPE_CHECKING:
    from src.screenshot_review import ReviewedScreenshot


def create_blueprint(*, resolve_review: Callable[[str], tuple[Path, Mapping[str, object]] | None],
                     authenticated: Callable[[], bool], csrf_valid: Callable[[], bool], same_origin: Callable[[], bool], csrf_token: Callable[[], str]) -> Blueprint:
    bp = Blueprint('screenshot_intelligence', __name__)
    analyzer = ImageAnalyzer()
    lock = threading.Lock()

    @bp.before_request
    def protect():
        if not authenticated():
            return jsonify(error='Authentication required'), 401
        if request.method == 'POST' and (not csrf_valid() or not same_origin()):
            return jsonify(error='Invalid CSRF or origin'), 403
        return None

    def resolve():
        from src.screenshot_review import list_review_items

        session = request.args.get('session_id', '')
        result = resolve_review(session) if session and len(session) <= 200 else None
        if result is None:
            raise ValueError('Review session unavailable')
        root, meta = result
        return root, list_review_items(root, meta)

    def decisions(root: Path) -> dict[str, dict[str, str]]:
        path = root / 'screenshot_intelligence_decisions.json'
        try:
            if path.is_symlink() or path.stat().st_size > 65536:
                return {}
            value: dict[str, dict[str, str]] = json.loads(path.read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def report(root: Path, items: list[ReviewedScreenshot]) -> dict[str, Any]:
        from src.screenshot_review import image_version

        result = analyzer.review(items, root, version=lambda i: image_version(root, i.id, 0))
        saved = decisions(root)
        for row in result['images']:
            value = saved.get(row['id'], {})
            row['decision'] = value.get('decision', 'unreviewed') if value.get('version') == row.get('version') and row.get('version') else 'unreviewed'
        return result

    @bp.get('/screenshot-intelligence')
    def page():
        return render_template('screenshot_intelligence.html', csrf_token=csrf_token())

    @bp.get('/api/screenshot-intelligence')
    def analysis():
        try:
            root, items = resolve()
            with lock:
                result = report(root, items)
            response = jsonify(result)
            response.headers['Cache-Control'] = 'no-store'
            return response
        except ValueError:
            return jsonify(error='Review session unavailable'), 404

    @bp.get('/api/screenshot-intelligence/<identity>/thumbnail')
    def thumbnail(identity):
        from src.screenshot_review import image_version

        try:
            root, items = resolve()
            item = next((i for i in items[:MAX_IMAGES] if i.id == identity and i.path is not None), None)
            if item is None or item.path is None:
                raise ValueError('Local image unavailable')
            result = analyzer.inspect(item.path, root, image_version(root, item.id, 0))
            return Response(result['thumbnail'], mimetype='image/jpeg', headers={'Cache-Control': 'private, max-age=0', 'X-Content-Type-Options': 'nosniff'})
        except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            return jsonify(error='Local image unavailable'), 404

    @bp.post('/api/screenshot-intelligence/decision')
    def decision():
        try:
            root, items = resolve()
            data: dict[str, Any] | None = request.get_json(silent=True)
            if not isinstance(data, dict) or data.get('decision') not in ('accepted', 'rejected', 'unreviewed'):
                raise ValueError('Invalid decision')
            with lock:
                result = report(root, items)
                row = next((r for r in result['images'] if r['id'] == data.get('id')), None)
                if row is None or not row.get('version') or row['version'] != data.get('version'):
                    return jsonify(error='Image changed; refresh review'), 409
                saved = decisions(root)
                current = {r['id'] for r in result['images']}
                saved = {k: v for k, v in saved.items() if k in current}
                saved[row['id']] = {'version': row['version'], 'decision': data['decision']}
                fd, temporary = tempfile.mkstemp(prefix='.image-decisions-', dir=root)
                try:
                    with os.fdopen(fd, 'w') as stream:
                        json.dump(saved, stream)
                    Path(temporary).replace(root / 'screenshot_intelligence_decisions.json')
                finally:
                    Path(temporary).unlink(missing_ok=True)
            return jsonify(saved=True)
        except (TypeError, ValueError):
            return jsonify(error='Invalid session or decision'), 400

    return bp
