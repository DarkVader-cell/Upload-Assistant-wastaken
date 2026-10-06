"""Bounded live terminal buffering with cancellable producer backpressure."""
import queue
import threading


class TerminalOutputQueue(queue.Queue[tuple[str, str]]):
    """Preserve output while connected; release blocked writers on disconnect."""

    def __init__(self, maxsize: int = 8192) -> None:
        if maxsize <= 0:
            raise ValueError("Terminal output capacity must be positive")
        super().__init__(maxsize=maxsize)
        self._closed = threading.Event()

    def write(self, origin: str, text: str) -> None:
        while not self._closed.is_set():
            try:
                self.put((origin, text), timeout=0.1)
                return
            except queue.Full:
                continue

    def close(self) -> None:
        self._closed.set()
