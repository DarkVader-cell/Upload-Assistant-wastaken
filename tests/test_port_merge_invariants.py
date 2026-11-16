"""Regression checks for the upstream-port merge boundaries."""
import ast
from pathlib import Path

from src.meta import Meta

ROOT = Path(__file__).resolve().parents[1]


def test_upload_pipeline_has_one_definition_and_confirmation_handler():
    tree = ast.parse((ROOT / "upload.py").read_text(encoding="utf-8"))
    functions = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert functions.count("process_meta") == 1
    calls_handler = any(isinstance(node, ast.Name) and node.id == "_handle_edit_confirmation_loop" and isinstance(node.ctx, ast.Load) for node in ast.walk(tree))
    assert not calls_handler or functions.count("_handle_edit_confirmation_loop") == 1


def test_legacy_tracker_metadata_defaults_are_independent():
    first, second = Meta(), Meta()
    assert first.were_trumping is False
    assert first.trump_reason is None
    assert first.trumpable_id is None
    assert first.season_pack_contains_episode is None
    assert first.screenshots_reported_torrent is None
    assert first.screenshots_trumping_torrent is None
    first.skip_upload_trackers.append("AITHER")
    assert second.skip_upload_trackers == []
