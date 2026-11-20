from unittest.mock import Mock

import pytest

from web_ui import server


def test_scheduler_skips_session_without_launch(monkeypatch):
    state = {"scheduled": True, "run_token": "x", "finished": False}
    monkeypatch.setattr(server, "active_processes", {"s": state})
    monkeypatch.setattr(server, "_session_is_running", lambda _state: True)
    launch = Mock()
    monkeypatch.setattr(server, "_launch_session", launch)
    server._start_scheduled_sessions()
    launch.assert_not_called()
    assert state["scheduled"] is True


def test_queue_release_keeps_another_sessions_queue(monkeypatch, tmp_path):
    queue_file = tmp_path / "queue.txt"
    queue_file.write_text("payload\n")
    key = str(queue_file.resolve())
    owner = {"execution_path": key}
    other = {"execution_path": key}
    monkeypatch.setattr(server, "active_processes", {"owner": owner, "other": other})
    monkeypatch.setattr(server, "_generated_queues", {key: "hash"})
    monkeypatch.setattr(server, "_session_is_running", lambda _: True)
    remove = Mock()
    monkeypatch.setattr(server, "_remove_generated_queue_file", remove)
    server._release_session_queue_file(key, owner)
    remove.assert_not_called()
    assert key in server._generated_queues


def test_launch_thread_failure_terminates_process(monkeypatch):
    process = Mock()
    state = {"run_token": "x", "launch": ([], server.Path("."), {})}
    monkeypatch.setattr(server, "active_processes", {"s": state})
    monkeypatch.setattr(server, "_spawn_webui_upload_process", lambda *_: (process, "pipe"))
    terminate, close = Mock(), Mock()
    monkeypatch.setattr(server, "_terminate_process_tree", terminate)
    monkeypatch.setattr(server, "_close_webui_process_io", close)
    thread = Mock()
    thread.start.side_effect = RuntimeError("thread failed")
    monkeypatch.setattr(server.threading, "Thread", lambda **_: thread)
    with pytest.raises(RuntimeError, match="thread failed"):
        server._launch_session("s", state)
    terminate.assert_called_once_with(process)
    close.assert_called_once_with(process)
