"""Atomic stage-level checkpoint persistence for resumable pipelines."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.runtime.state import atomic_write_json, default_config, read_json, safe_digest, safe_state_snapshot

CHECKPOINT_VERSION = 1


class CheckpointStore:
    def __init__(self, base_dir: str | Path, config: Mapping[str, Any] | None = None) -> None:
        settings = default_config(config)
        self.enabled = bool(settings.get("stage_checkpoints_enabled", True))
        configured = Path(str(settings.get("stage_checkpoints_dir", "data/cache/checkpoints")))
        base = Path(base_dir).resolve()
        self.root = configured if configured.is_absolute() else base / configured

    def path_for(self, run_key: str) -> Path:
        return self.root / f"{safe_digest(run_key)}.json"

    def _load_sync(self, run_key: str, pipeline_signature: str) -> dict[str, Any]:
        raw = read_json(self.path_for(run_key))
        if not isinstance(raw, dict) or raw.get("version") != CHECKPOINT_VERSION or raw.get("pipeline") != pipeline_signature:
            return {"version": CHECKPOINT_VERSION, "pipeline": pipeline_signature, "stages": {}}
        stages = raw.get("stages")
        if not isinstance(stages, dict):
            raw["stages"] = {}
        return raw

    async def completed_snapshot(self, run_key: str, pipeline_signature: str, stage: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        state = await asyncio.to_thread(self._load_sync, run_key, pipeline_signature)
        item = state["stages"].get(stage)
        if not isinstance(item, dict) or item.get("status") != "completed" or not isinstance(item.get("meta"), dict):
            return None
        return dict(item["meta"])

    def _mark_sync(self, run_key: str, pipeline_signature: str, stage: str, status: str, meta: Mapping[str, Any], detail: str) -> None:
        state = self._load_sync(run_key, pipeline_signature)
        state["updated_at"] = time.time()
        state["stages"][stage] = {"status": status, "detail": detail, "updated_at": time.time(), "meta": safe_state_snapshot(meta)}
        atomic_write_json(self.path_for(run_key), state)

    async def mark_completed(self, run_key: str, pipeline_signature: str, stage: str, meta: Mapping[str, Any], detail: str = "") -> None:
        if self.enabled:
            await asyncio.to_thread(self._mark_sync, run_key, pipeline_signature, stage, "completed", meta, detail)

    async def mark_stopped(self, run_key: str, pipeline_signature: str, stage: str, meta: Mapping[str, Any], detail: str = "") -> None:
        if self.enabled:
            await asyncio.to_thread(self._mark_sync, run_key, pipeline_signature, stage, "stopped", meta, detail)

    async def clear(self, run_key: str) -> None:
        if self.enabled:
            await asyncio.to_thread(self.path_for(run_key).unlink, missing_ok=True)

    def stats(self) -> dict[str, int]:
        files = list(self.root.glob("*.json")) if self.root.exists() else []
        completed = 0
        for path in files:
            state = read_json(path)
            if isinstance(state, dict) and isinstance(state.get("stages"), dict):
                completed += sum(1 for item in state["stages"].values() if isinstance(item, dict) and item.get("status") == "completed")
        return {"runs": len(files), "completed_stages": completed}
