"""Authenticated API for durable release history."""

from __future__ import annotations

import sqlite3
from typing import Any

from flask import Blueprint, jsonify, request

from src.runtime.history import ReleaseHistoryStore

_ALLOWED_STATUSES = {"", "cancelled", "completed", "debug", "failed", "interrupted", "queued", "running", "skipped"}


def create_history_api_blueprint(*, auth_check: Any, history: ReleaseHistoryStore, json_safe: Any) -> Blueprint:
    blueprint = Blueprint("history_api", __name__)

    @blueprint.route("/api/release_history")
    def release_history():
        """Search durable release history across CLI, Web UI, and Qui runs."""
        ok, response = auth_check()
        if not ok:
            return response
        try:
            limit = max(1, min(int(request.args.get("limit", "100")), 500))
            offset = max(0, int(request.args.get("offset", "0")))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Invalid pagination"}), 400
        query = str(request.args.get("q", "")).strip()[:200]
        status = str(request.args.get("status", "")).strip().casefold()
        if status not in _ALLOWED_STATUSES:
            return jsonify({"success": False, "error": "Invalid history status"}), 400
        try:
            items = history.search(query, status, limit=limit, offset=offset)
            stats = history.stats()
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return jsonify({"success": False, "error": "Release history is temporarily unavailable"}), 503
        return jsonify({"success": True, "items": json_safe(items), "stats": stats, "limit": limit, "offset": offset})

    return blueprint
