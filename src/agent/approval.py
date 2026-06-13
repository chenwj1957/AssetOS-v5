from __future__ import annotations

import threading


class ApprovalGate:
    """Blocks an in-flight run until a human approves or denies a gated tool call.

    One gate is shared per chat request. ``wait`` is called from the agent
    loop thread and polls until ``resolve`` is called from the HTTP request
    thread handling the user's approve/deny click, the run is cancelled, or
    the timeout elapses (treated as a denial so the worker can never hang
    forever if the user walks away).
    """

    def __init__(self, poll_interval: float = 0.2, timeout: float = 600.0) -> None:
        self._event = threading.Event()
        self._approved = False
        self.poll_interval = poll_interval
        self.timeout = timeout

    def wait(self, cancel_event: threading.Event | None = None) -> bool:
        self._event.clear()
        self._approved = False
        elapsed = 0.0
        while not self._event.is_set():
            if cancel_event is not None and cancel_event.is_set():
                return False
            if elapsed >= self.timeout:
                return False
            self._event.wait(timeout=self.poll_interval)
            elapsed += self.poll_interval
        return self._approved

    def resolve(self, approved: bool) -> None:
        self._approved = approved
        self._event.set()
