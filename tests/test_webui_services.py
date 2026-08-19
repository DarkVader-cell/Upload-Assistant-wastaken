# ruff: noqa: S101

import json

from web_ui.services.detached_jobs import restore_detached_jobs, snapshot_detached_jobs, validate_detached_args
from web_ui.services.presets import load_argument_presets, save_argument_presets


def test_argument_presets_are_normalized_capped_and_atomic(tmp_path):
    path = tmp_path / "presets.json"
    save_argument_presets(path, [{"name": " First ", "arguments": " -ua "}, {"name": "Second", "arguments": "--debug"}])
    assert load_argument_presets(path, 1) == [{"name": "Second", "arguments": "--debug"}]
    assert not path.with_suffix(".json.tmp").exists()


def test_detached_restore_interrupts_inflight_jobs_without_replaying(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text(
        json.dumps(
            {
                "running": {"id": "running", "status": "running", "command": ["python", "upload.py"]},
                "queued": {"id": "queued", "status": "queued", "command": ["python", "upload.py"]},
            }
        ),
        encoding="utf-8",
    )
    restored = restore_detached_jobs(path)
    assert restored is not None
    assert restored.jobs["running"]["status"] == "interrupted"
    assert restored.queue == ["queued"]


def test_detached_snapshot_redacts_commands_and_sets_capabilities():
    snapshots = snapshot_detached_jobs(
        {"job": {"id": "job", "status": "queued", "command": ["secret"], "created_at": "1"}},
        ["job"],
        limit=10,
        json_safe=lambda value: value,
    )
    assert snapshots == [
        {
            "id": "job",
            "status": "queued",
            "created_at": "1",
            "queue_position": 1,
            "can_edit": True,
            "can_cancel": True,
            "can_retry": False,
        }
    ]


def test_detached_argument_validation_keeps_unattended_compatibility():
    validated, rendered = validate_detached_args('--trackers "OE, AITHER"', True, lambda args: list(args))
    assert validated == ["--trackers", "OE, AITHER", "-ua"]
    assert rendered == "--trackers OE, AITHER -ua"
