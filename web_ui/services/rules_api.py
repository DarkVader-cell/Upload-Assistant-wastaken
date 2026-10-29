"""Authenticated visual rule editing and preview against recorded candidates only."""
from flask import Blueprint, jsonify, render_template, request

from src.automation_rules import ACTIONS, FIELDS, MAX_BYTES, OPERATORS, REQUIREMENTS, evaluate, validate_schema


def create_blueprint(*, store, references, candidates, authenticated, csrf_valid, same_origin, csrf_token):
    bp = Blueprint('automation_rules', __name__)

    @bp.before_request
    def protect():
        request.max_content_length = MAX_BYTES
        if not authenticated():
            return jsonify(error='Authentication required'), 401
        if request.method == 'POST' and (not csrf_valid() or not same_origin()):
            return jsonify(error='Invalid CSRF or origin'), 403
        return None

    @bp.get('/automation-rules')
    def page():
        return render_template('automation_rules.html', csrf_token=csrf_token())

    @bp.get('/api/automation-rules')
    def read():
        try:
            refs = references()
            schema, revision = store.load(refs)
            return jsonify(schema=schema, revision=revision, references=refs, fields=FIELDS, operators=OPERATORS, actions=ACTIONS, requirements=REQUIREMENTS)
        except (OSError, TypeError, ValueError):
            return jsonify(error='Rule state unavailable or references changed'), 503

    @bp.post('/api/automation-rules')
    def save():
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict) or set(data) != {'schema', 'revision'}:
                raise ValueError('Invalid save request')
            schema, revision = store.save(data['schema'], data['revision'], references())
            return jsonify(schema=schema, revision=revision)
        except FileExistsError:
            return jsonify(error='Rules changed; reload before saving'), 409
        except (TypeError, ValueError, RecursionError):
            return jsonify(error='Invalid rule schema or references'), 400
        except OSError:
            return jsonify(error='Rule state is not writable'), 503

    @bp.get('/api/automation-rules/candidates')
    def listing():
        return jsonify(candidates=[{'id': r['id'], 'label': r['release_name']} for r in candidates()[:200]])

    @bp.post('/api/automation-rules/preview')
    def preview():
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict) or set(data) - {'id', 'schema'}:
                raise ValueError('Invalid preview')
            candidate = next((r for r in candidates() if r['id'] == data.get('id')), None)
            if candidate is None:
                raise ValueError('Unknown recorded candidate')
            refs = references()
            schema = validate_schema(data['schema'], refs) if 'schema' in data else store.load(refs)[0]
            return jsonify(evaluate(schema, candidate))
        except (TypeError, ValueError, RecursionError):
            return jsonify(error='Invalid candidate or rule schema'), 400

    return bp
