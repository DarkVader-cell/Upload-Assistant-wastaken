"""Bounded operator snapshot imports. Deliberately no execution endpoints."""
import time

from flask import Blueprint, jsonify, render_template, request

from src.migration_planner import MAX_BYTES, plan


def example_snapshot(now):
    """Incomplete by design: importing the template cannot imply readiness."""
    return {'version': 1, 'source': 'operator-example-not-live', 'observed_at': now,
            'destination': {'id': 'Grape', 'role': 'grape', 'capacity_bytes': 1000000000000, 'used_bytes': 500000000000,
                            'pending_bytes': 0, 'headroom_bytes': 100000000000, 'observed_at': now, 'estimated_bytes_per_second': 10000000},
            'candidates': [{'label': 'Example only', 'infohash': 'a' * 40, 'size_bytes': 10000000000, 'origin_kind': 'historical', 'state': 'recovery-required',
                            'related_handoffs': None, 'tree': {'kind': 'file', 'complete': False, 'observed_at': None, 'entries': []}}]}


def create_blueprint(*, authenticated, csrf_valid, same_origin, csrf_token):
    bp = Blueprint('migration_planner', __name__)

    @bp.before_request
    def protect():
        request.max_content_length = MAX_BYTES
        if not authenticated():
            return jsonify(error='Authentication required'), 401
        if request.method == 'POST' and (not csrf_valid() or not same_origin()):
            return jsonify(error='Invalid CSRF or origin'), 403
        return None

    @bp.get('/migration-planner')
    def page():
        return render_template('migration_planner.html', csrf_token=csrf_token())

    @bp.get('/api/migration-planner/example')
    def example():
        return jsonify(example_snapshot(time.time()))

    @bp.post('/api/migration-planner/preview')
    def preview():
        try:
            result = plan(request.get_json(silent=True), now=time.time())
            response = jsonify(result)
            response.headers['Cache-Control'] = 'no-store'
            return response
        except (ValueError, TypeError, RecursionError):
            return jsonify(error='Invalid snapshot schema, evidence or capacity. No server paths or credentials are accepted.'), 400

    return bp
