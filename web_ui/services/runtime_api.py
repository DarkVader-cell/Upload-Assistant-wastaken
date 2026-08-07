"""Runtime planning and health API blueprint kept outside the Web UI monolith."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from src.args import Args
from src.meta import Meta
from src.runtime.context import ExecutionContext
from src.runtime.health import collect_runtime_health
from src.runtime.planner import build_execution_plan


def create_runtime_api_blueprint(
    *,
    auth_check: Any,
    limiter: Any,
    basic_rate_key: Any,
    rate_limit_key: Any,
    resolve_user_path: Any,
    validate_args: Any,
    load_config: Any,
    project_root: Path,
) -> Blueprint:
    blueprint = Blueprint("runtime_api", __name__)

    def config() -> dict[str, Any]:
        return load_config(project_root / "data" / "config.py") or load_config(project_root / "data" / "example_config.py") or {}

    @blueprint.route("/api/health")
    @limiter.limit("70 per hour", key_func=basic_rate_key)
    def health():
        return jsonify({"status": "healthy", "success": True, "message": "Upload-Assistant Web UI is running"})

    @blueprint.route("/api/runtime/health")
    @limiter.limit("120 per hour", key_func=rate_limit_key)
    def runtime_health():
        ok, response = auth_check()
        if not ok:
            return response
        return jsonify({"success": True, **collect_runtime_health(project_root, config())})

    @blueprint.route("/api/plan", methods=["POST"])
    @limiter.limit("300 per hour", key_func=rate_limit_key)
    def execution_plan():
        ok, response = auth_check()
        if not ok:
            return response
        data = request.get_json(silent=True)
        data = data if isinstance(data, dict) else {}
        try:
            planned_path = resolve_user_path(str(data.get("path") or ""), require_exists=True, require_dir=False)
            validated_args, _ = validate_args(data.get("args", ""), False)
            loaded = config()
            plan_meta, _, _ = Args(loaded).parse([planned_path, *validated_args], Meta(base_dir=str(project_root)))
        except (SystemExit, TypeError, ValueError) as error:
            return jsonify({"success": False, "error": str(error) or "Invalid plan request"}), 400

        async def create_plan() -> dict[str, Any]:
            async with ExecutionContext.create(project_root, loaded) as context:
                return (await build_execution_plan(context, plan_meta, planned_path)).to_dict()

        return jsonify({"success": True, "plan": asyncio.run(create_plan())})

    return blueprint
