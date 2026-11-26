# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A task whose call runs in a process of its own."""

from __future__ import annotations

import contextlib
import functools
import multiprocessing as mp
import pickle
import threading
import traceback
from collections.abc import Callable
from multiprocessing.connection import Connection, wait
from multiprocessing.process import BaseProcess
from typing import Any

from .errors import ProcessExitError, StoppedError
from .stop import StopToken
from .task import _label, _Task
from .thread import _ThreadTask

# Seconds a child gets after terminate(), then after kill(), once the
# runtime's stop has given up on it
_GRACE = 2.0


class _ProcessTask(_ThreadTask):
    """Calls a function in a child process, started with the ``spawn`` method:
    the function and its arguments are pickled, and the function is found by
    import in the child. A thread of the parent's starts the child and waits
    for it, so the task is waited for, cancelled and joined as a thread task.

    The child runs the call as a thread task of its own, inline: stopping()
    and task_id() work there, with this task's id. Its token stops when this
    task's does, or when the parent's end of the stop connection closes, so a
    child outliving its parent stops. The outcome comes back over a second
    connection: the result, the exception with the child's traceback as its
    cause, or the stop. A child that exits without one fails the task with
    ProcessExitError, unless the task was stopped.
    """

    __slots__ = ("_process",)

    def __init__(
        self,
        on_end: Callable[[_Task], None],
        task_id: int,
        name: str | None,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        token: StopToken,
    ) -> None:
        """Initialize task; see _Task."""
        super().__init__(on_end, task_id, name, fn, args, token)
        self._process: BaseProcess | None = None

    def _call(self, fn: Callable[..., Any], args: tuple[Any, ...]) -> Any:
        """Run *fn*(*args*) in a child and return or raise its outcome."""
        ctx = mp.get_context("spawn")
        outcome_recv, outcome_send = ctx.Pipe(duplex=False)
        stop_recv, stop_send = ctx.Pipe(duplex=False)
        unregister = self.token._on_stop(functools.partial(_signal, stop_send))
        try:
            process = ctx.Process(
                target=_child,
                args=(self.id, self.name, fn, args, stop_recv, outcome_send),
                name=_label(self.id, self.name),
            )
            process.start()
            self._process = process
            # The child has its copies: EOF on either side means the other end
            # is gone
            stop_recv.close()
            outcome_send.close()
            return self._outcome(process, outcome_recv)
        finally:
            unregister()
            for conn in (outcome_recv, outcome_send, stop_recv, stop_send):
                conn.close()

    def _outcome(self, process: BaseProcess, outcome: Connection) -> Any:
        """Wait for the child to report its outcome or exit; return or raise
        the outcome."""
        wait([outcome, process.sentinel])
        payload: bytes | None = None
        if outcome.poll():
            with contextlib.suppress(EOFError, OSError):
                payload = outcome.recv_bytes()
        process.join()
        if payload is None:
            if self.token.is_set():
                raise StoppedError()
            raise ProcessExitError(self.id, process.exitcode)
        result, error, text, stopped = pickle.loads(payload)
        if stopped:
            raise StoppedError()
        if error is not None:
            error.__cause__ = _ChildError(text)
            raise error
        return result

    def force(self) -> bool:
        """Terminate the child, then kill it, and wait for this task's end."""
        process = self._process
        if process is not None and process.is_alive():
            process.terminate()
            process.join(_GRACE)
            if process.is_alive():
                process.kill()
                process.join(_GRACE)
        return self.join(_GRACE)


class _ChildError(Exception):
    """The traceback of an exception raised in a task's child process, as the
    child formatted it: the cause of that exception as the parent raises it."""

    def __init__(self, text: str) -> None:
        """The child's traceback, formatted."""
        super().__init__(text)
        self.text = text

    def __str__(self) -> str:
        """The traceback, as the child printed it."""
        return f"\n{self.text}"


def _signal(stop: Connection) -> None:
    """Stop callback: tell the child to stop. A write that never waits for the
    reader; a child already gone, or a connection closed meanwhile, needs no
    signal."""
    with contextlib.suppress(OSError, ValueError):
        stop.send_bytes(b"")


def _child(
    task_id: int,
    name: str | None,
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    stop: Connection,
    outcome: Connection,
) -> None:
    """The child's main: run the call as a thread task, inline, and send its
    outcome; its token stops on a signal or EOF on *stop*."""
    token = StopToken()
    threading.Thread(
        target=_stop_on_signal, args=(stop, token), name="stop", daemon=True
    ).start()
    report = functools.partial(_report, outcome=outcome)
    task = _ThreadTask(report, task_id, name, fn, args, token)
    task._context.run(task._run)


def _stop_on_signal(stop: Connection, token: StopToken) -> None:
    """Stop *token* once the parent signals or its end of *stop* closes."""
    with contextlib.suppress(EOFError, OSError):
        stop.recv_bytes()
    token.stop()


def _report(task: _Task, outcome: Connection) -> None:
    """Send *task*'s outcome to the parent: pickled, once the bytes unpickle
    here; else a RuntimeError naming why, in place of its result and error."""
    error = task.exception
    text = "" if error is None else "".join(traceback.format_exception(error))
    try:
        payload = pickle.dumps((task.result, error, text, task.stopped))
        pickle.loads(payload)
    except Exception as e:
        failure = RuntimeError(f"task {task.id} ended unpicklable: {e!r}")
        payload = pickle.dumps((None, failure, text, False))
    outcome.send_bytes(payload)
