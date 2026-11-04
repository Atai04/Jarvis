"""Real POSIX terminal queues, without microphone, playback, or network access."""

import asyncio
import os
import select
import termios

import pytest

from app.utils.terminal_input import confirmation_input, suppress_terminal_input


@pytest.fixture
def terminal():
    master, slave = os.openpty()
    try:
        yield master, slave
    finally:
        os.close(master)
        os.close(slave)


def test_unsuppressed_terminal_reproduces_typeahead(terminal):
    master, slave = terminal
    os.write(master, b"exit\nq\n\n")
    assert select.select([slave], [], [], 1)[0]
    assert os.read(slave, 100) == b"exit\n"
    assert os.read(slave, 100) == b"q\n"
    assert os.read(slave, 100) == b"\n"


def test_suppression_drops_playback_typeahead_and_restores_modes(terminal):
    master, slave = terminal
    original = termios.tcgetattr(slave)
    with suppress_terminal_input(slave):
        attrs = termios.tcgetattr(slave)
        assert not attrs[3] & termios.ECHO
        assert attrs[3] & termios.ISIG == original[3] & termios.ISIG
        os.write(master, b"exit\nq\n\nyes\npartial")
        assert select.select([slave], [], [], 1)[0]
    assert termios.tcgetattr(slave) == original
    assert not select.select([slave], [], [], 0)[0]
    os.write(master, b"fresh\n")
    assert select.select([slave], [], [], 1)[0]
    assert os.read(slave, 100) == b"fresh\n"


def test_only_permission_prompt_accepts_input(terminal):
    master, slave = terminal
    original = termios.tcgetattr(slave)
    with suppress_terminal_input(slave):
        os.write(master, b"yes\n")  # Premature approval must be dropped.
        assert select.select([slave], [], [], 1)[0]
        with confirmation_input():
            assert termios.tcgetattr(slave) == original
            assert not select.select([slave], [], [], 0)[0]
            os.write(master, b"n\n")
            assert select.select([slave], [], [], 1)[0]
            assert os.read(slave, 100) == b"n\n"
            os.write(master, b"exit\n")
            assert select.select([slave], [], [], 1)[0]
        assert not termios.tcgetattr(slave)[3] & termios.ECHO
        assert not select.select([slave], [], [], 0)[0]
    assert termios.tcgetattr(slave) == original


@pytest.mark.parametrize("cancel", [True, False])
async def test_failure_and_cancellation_restore_terminal(terminal, cancel):
    master, slave = terminal
    original = termios.tcgetattr(slave)
    entered = asyncio.Event()

    async def work():
        with suppress_terminal_input(slave):
            os.write(master, b"exit\n")
            assert select.select([slave], [], [], 1)[0]
            entered.set()
            if not cancel:
                raise RuntimeError("test failure")
            await asyncio.Future()

    task = asyncio.create_task(work())
    await entered.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await task
    assert termios.tcgetattr(slave) == original
    assert not select.select([slave], [], [], 0)[0]


def test_interrupted_confirmation_restores_terminal(terminal):
    master, slave = terminal
    original = termios.tcgetattr(slave)
    with (
        pytest.raises(KeyboardInterrupt),
        suppress_terminal_input(slave),
        confirmation_input(),
    ):
        assert termios.tcgetattr(slave) == original
        os.write(master, b"exit\n")
        assert select.select([slave], [], [], 1)[0]
        raise KeyboardInterrupt
    assert termios.tcgetattr(slave) == original
    assert not select.select([slave], [], [], 0)[0]
