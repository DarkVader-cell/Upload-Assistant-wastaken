"""Opt-in discovery snapshot API; no crawling, client mutations or execution."""
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, render_template, request

from src.discovery import FIELDS, candidates, preview, select


def create_blueprint(*, records: Callable[[], Iterable[Mapping[str, Any]]], roots: Callable[[], list[str | Path]], trackers: Callable[[], Iterable[str]],
                     validate_path: Callable[[str], str], authenticated: Callable[[], bool], csrf_valid: Callable[[], bool],
                     same_origin: Callable[[], bool], csrf_token: Callable[[], str]) -> Blueprint:
    bp = Blueprint('discovery', __name__)
    lock = threading.Lock()
    snapshot: dict[str, Any] = {'rows': [], 'truncated': False, 'updated_at': None}

    @bp.before_request
    def protect():
        if not authenticated():
            return jsonify(error='Authentication required'), 401
        if request.method == 'POST' and (not csrf_valid() or not same_origin()):
            return jsonify(error='Invalid CSRF or origin'), 403
        return None

    @bp.get('/discovery')
    def page():
        return render_template('discovery.html', csrf_token=csrf_token())

    def targets(values: list[str], required: bool = False) -> list[str]:
        if not isinstance(values, list) or len(values) > 200 or any(not isinstance(v, str) for v in values) or set(values) - set(trackers()) or (required and not values):
            raise ValueError('Select configured trackers')
        return values

    @bp.post('/api/discovery/refresh')
    def refresh():
        with lock:
            now = time.time()
            rows, truncated = candidates(records(), roots(), now=now)
            snapshot.update(rows=rows, truncated=truncated, updated_at=now)
        return jsonify(updated_at=now, total=len(rows), truncated=truncated)

    @bp.get('/api/discovery')
    def listing():
        try:
            with lock:
                result = select(snapshot['rows'], trackers=targets(request.args.getlist('tracker')), mode=request.args.get('mode', 'missing'),
                                query=request.args.get('q', ''), filters={f: request.args.get(f, '') for f in FIELDS},
                                offset=int(request.args.get('offset', 0)), limit=int(request.args.get('limit', 100)))
                result.update(updated_at=snapshot['updated_at'], truncated=snapshot['truncated'], trackers=sorted(trackers()),
                              facets={f: sorted({r[f] for r in snapshot['rows'] if r[f]}) for f in FIELDS})
            return jsonify(result)
        except (TypeError, ValueError):
            return jsonify(error='Invalid discovery filters'), 400

    @bp.post('/api/discovery/preview')
    def plan():
        try:
            data: dict[str, Any] | None = request.get_json(silent=True)
            if not isinstance(data, dict):
                raise ValueError('Invalid selection')
            selected = targets(data.get('trackers', []), required=True)
            with lock:
                result = preview(snapshot['rows'], data.get('ids', []), selected, validate_path)
            return jsonify(result)
        except (TypeError, ValueError):
            return jsonify(error='Invalid discovery selection'), 400

    return bp
