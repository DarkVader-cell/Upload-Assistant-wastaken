import asyncio

from cogs.redaction import Redaction
from src.manual_metadata import metadata_request, parse_metadata_submission, should_request_metadata
from src.modified_release import MODIFIED_RELEASE_REASON, detect_modified_release
from src.safe_url import UnsafeURL, assert_public_http_url
from upload import queue_item_has_successful_upload
from web_ui import server as webui_server


def test_detached_metadata_policy_respects_optional_and_no_prompt_flags():
    base = {"tmdb_id": 123, "imdb_id": 0, "category": "MOVIE"}
    assert should_request_metadata(base, detached=True)
    assert not should_request_metadata({**base, "imdb_optional": True}, detached=True)
    assert not should_request_metadata({**base, "no_prompt_missing_ids": True}, detached=True)
    assert metadata_request({**base, "imdb_optional": True})["missing"] == []


def test_metadata_submission_normalizes_tmdb_and_imdb_ids():
    assert parse_metadata_submission({"tmdb_id": "tv/123", "imdb_id": "tt456"}) == {
        "tmdb_id": 123,
        "imdb_id": 456,
        "category": "TV",
    }


def test_modified_release_detection_allows_discs_and_personal_releases():
    assert detect_modified_release(["/media/Movie {tmdb-123}.mkv"]) == MODIFIED_RELEASE_REASON
    assert detect_modified_release(["/media/Movie {tmdb-123}.mkv"], is_disc=True) is None
    assert detect_modified_release(["/media/Movie {tmdb-123}.mkv"], personal_release=True) is None


def test_redaction_covers_headers_paths_and_query_values():
    value = "Authorization: Bearer secret, Cookie: sid=private; token=hidden https://x.test/announce/abc123456789?api_key=private"
    redacted = Redaction.redact_value(value)
    assert "abc123456789" not in redacted
    assert "private" not in redacted
    assert Redaction.redact_private_info({"Api-Key": "secret"})["Api-Key"] == "[REDACTED]"


def test_safe_url_rejects_private_network_targets():
    async def check() -> None:
        try:
            await assert_public_http_url("http://127.0.0.1/image.jpg")
        except UnsafeURL:
            return
        raise AssertionError("private URL was accepted")

    asyncio.run(check())


def test_detached_qui_restore_marks_inflight_jobs_retryable(tmp_path, monkeypatch):
    state_path = tmp_path / "qui_jobs.json"
    state_path.write_text(
        '{"job-1": {"id": "job-1", "status": "running", '
        '"command": ["python", "upload.py", "/media/item"], '
        '"source_path": "/media/item"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(webui_server, "DETACHED_JOB_STATE_PATH", state_path)
    with webui_server.detached_jobs_lock:
        webui_server.detached_jobs.clear()
        webui_server.detached_job_queue.clear()

    webui_server._restore_detached_jobs()

    assert webui_server.detached_jobs["job-1"]["status"] == "interrupted"
    assert webui_server.detached_jobs["job-1"]["recovery_available"] is True
    assert webui_server.detached_job_queue == []


def test_detached_operation_arguments_are_validated_and_unattended():
    validated, display = webui_server._validated_detached_args('--trackers "OE, MTV"')
    assert validated[-1] == "-ua"
    assert display.endswith("-ua")


def test_detached_job_snapshot_exposes_safe_control_capabilities():
    with webui_server.detached_jobs_lock:
        webui_server.detached_jobs.clear()
        webui_server.detached_job_queue.clear()
        webui_server.detached_jobs["queued-1"] = {
            "id": "queued-1",
            "status": "queued",
            "source_path": "/media/item",
            "args": "-ua",
            "command": ["python", "upload.py", "/media/item", "-ua"],
        }
        webui_server.detached_job_queue.append("queued-1")

    snapshot = webui_server._detached_job_snapshot()
    assert snapshot[0]["queue_position"] == 1
    assert snapshot[0]["can_edit"] is True
    assert snapshot[0]["can_cancel"] is True
    assert "command" not in snapshot[0]
    with webui_server.detached_jobs_lock:
        webui_server.detached_jobs.clear()
        webui_server.detached_job_queue.clear()


def test_failed_unattended_queue_item_remains_retryable():
    assert not queue_item_has_successful_upload([{"upload_success": False}])
    assert queue_item_has_successful_upload([{"upload_success": True}])
    assert queue_item_has_successful_upload([], debug=True)
