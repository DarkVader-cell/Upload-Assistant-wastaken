"""Check terminal backpressure and disconnect cleanup."""
# ruff: noqa: S101
import threading

import pytest

from web_ui.services.output_queue import TerminalOutputQueue


def test_queue_preserves_output_order():
    buffer = TerminalOutputQueue(2)
    buffer.write("stdout", "a")
    buffer.write("stderr", "b")
    assert buffer.get_nowait() == ("stdout", "a")
    assert buffer.get_nowait() == ("stderr", "b")


def test_full_queue_writer_released_on_disconnect():
    buffer = TerminalOutputQueue(1)
    buffer.write("stdout", "a")
    started = threading.Event()

    def writer():
        started.set()
        buffer.write("stdout", "b")

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    assert started.wait(1)
    buffer.close()
    thread.join(1)
    assert not thread.is_alive()
    assert buffer.qsize() == 1


def test_closed_queue_does_not_retain_more_output():
    buffer = TerminalOutputQueue(1)
    buffer.close()
    buffer.write("stdout", "discard")
    assert buffer.empty()


def test_queue_rejects_unbounded_capacity():
    with pytest.raises(ValueError):
        TerminalOutputQueue(0)
