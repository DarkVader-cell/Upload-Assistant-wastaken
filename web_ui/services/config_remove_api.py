"""Config subsection removal API kept outside the Web UI monolith."""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify

from web_ui.services.config_references import torrent_client_reference_updates


@dataclass(frozen=True)
class ConfigSourceOperations:
    load: Any
    remove_key: Any
    replace_value: Any
    python_literal: Any
    nested_value: Any
    audit: Any


def create_config_remove_blueprint(
    *,
    authenticated: Any,
    csrf_valid: Any,
    same_origin: Any,
    request_json: Any,
    project_root: Path,
    operations: ConfigSourceOperations,
) -> Blueprint:
    blueprint = Blueprint("config_remove_api", __name__)
    mutation_lock = threading.Lock()

    @blueprint.route("/api/config_remove_subsection", methods=["POST"])
    def config_remove_subsection():
        """Remove a subsection and repair references to deleted clients."""
        if not authenticated():
            return jsonify({"success": False, "error": "Authentication required (web session)"}), 401
        if not csrf_valid() or not same_origin():
            return jsonify({"success": False, "error": "CSRF/Origin validation failed"}), 403

        path_raw = request_json().get("path", [])
        path = [item for item in path_raw if isinstance(item, str) and item] if isinstance(path_raw, Sequence) and not isinstance(path_raw, (str, bytes, bytearray)) else []
        if not path:
            return jsonify({"success": False, "error": "Invalid path"}), 400

        config_path = project_root / "data" / "config.py"
        try:
            with mutation_lock:
                prior_config = operations.load(config_path) or {}
                source = config_path.read_text(encoding="utf-8")
                updated = operations.remove_key(source, path)
                if updated == source:
                    return jsonify({"success": True, "value": None})
                reference_updates: list[tuple[list[str], object | None]] = []
                if len(path) == 2 and path[0] == "TORRENT_CLIENTS":
                    reference_updates = torrent_client_reference_updates(prior_config, path[1])
                    for reference_path, value in reference_updates:
                        updated = (
                            operations.remove_key(updated, reference_path)
                            if value is None
                            else operations.replace_value(updated, reference_path, operations.python_literal(value))
                        )
                temporary = config_path.with_name(f".{config_path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
                try:
                    temporary.write_text(updated, encoding="utf-8")
                    temporary.replace(config_path)
                finally:
                    with contextlib.suppress(OSError):
                        temporary.unlink()
            changed_paths = [reference_path for reference_path, _value in reference_updates]
            with contextlib.suppress(Exception):
                operations.audit(
                    "remove_subsection",
                    path,
                    operations.nested_value(prior_config, path),
                    {"removed": True, "references_updated": changed_paths},
                    True,
                )
            return jsonify({"success": True, "references_updated": changed_paths})
        except Exception as error:
            with contextlib.suppress(Exception):
                operations.audit("remove_subsection", path, None, None, False, str(error))
            return jsonify({"success": False, "error": "An error occurred while removing the configuration subsection"}), 500

    return blueprint
