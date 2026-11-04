"""Scoped terminal ownership while asynchronous CLI work expects no input."""

import os
import termios
from contextlib import contextmanager
from contextvars import ContextVar

_active_guard = ContextVar("terminal_input_guard", default=None)


class _InputGuard:
    def __init__(self, fd):
        self.fd = fd
        self.original = termios.tcgetattr(fd)
        self.quiet = self.original.copy()
        # Keep canonical editing and ISIG (Ctrl-C) intact; hide idle typing.
        self.quiet[3] &= ~(termios.ECHO | termios.ECHONL)

    def suppress(self):
        self._apply(self.quiet)

    def restore(self):
        self._apply(self.original)

    def _apply(self, attributes):
        # TCSAFLUSH waits for output to drain and can block the event loop on a
        # flow-controlled terminal. Change modes immediately, then flush input only.
        termios.tcsetattr(self.fd, termios.TCSANOW, attributes)
        termios.tcflush(self.fd, termios.TCIFLUSH)


@contextmanager
def suppress_terminal_input(fd: int):
    """Flush queued input at both boundaries; never install a competing reader."""
    if not os.isatty(fd):
        yield
        return
    guard = _InputGuard(fd)
    token = _active_guard.set(guard)
    try:
        guard.suppress()
        yield
    finally:
        try:
            guard.restore()
        finally:
            _active_guard.reset(token)


@contextmanager
def confirmation_input():
    """Give a synchronous permission prompt sole ownership of terminal input."""
    guard = _active_guard.get()
    if guard is None:
        yield
        return
    guard.restore()  # Drop pretyped approvals before showing the prompt.
    try:
        yield
    finally:
        guard.suppress()  # Drop typeahead after approval/denial, even on interruption.
