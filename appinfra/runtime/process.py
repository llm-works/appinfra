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


class _ProcessTask(_ThreadTask):
    """Calls a function in a child process, started with the ``spawn`` method:
    the function and its arguments are pickled, and the function is found by
    import in the child. A thread of the parent's starts the child and waits
    for it, so the task is waited for, cancelled and joined as a thread task.

    The child runs the call as a thread task of its own, inline: stopping()
    and task_id() work there, with this task's id. Its token stops when this
    task's does, or when the parent's end of the stop connection closes, so a
    child outliving its parent stops. The outcome comes back over a second
    connection: the result, the exception with the child's traceback as a
    note (PEP 678), which, unlike a cause, survives any later pickling, as a
    done pipe's, or the stop. A child that exits without one fails the task with
    ProcessExitError, unless the task was stopped.
    """

    __slots__ = ("_process",)

    killable = True

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
        with contextlib.ExitStack() as ends:
            # Each end is closed on any exit from the moment it is opened
            outcome_recv, outcome_send = _opened(ends, ctx.Pipe(duplex=False))
            stop_recv, stop_send = _opened(ends, ctx.Pipe(duplex=False))
            ends.callback(self.token._on_stop(functools.partial(_signal, stop_send)))
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

    def _outcome(self, process: BaseProcess, outcome: Connection) -> Any:
        """Wait for the child to report its outcome or exit. A report is
        recorded on this task as the child made it, and its result returned.
        Without one: StoppedError if this task's token is stopped, else
        ProcessExitError, read as any call's error is (_raised())."""
        wait([outcome, process.sentinel])
        payload: bytes | None = None
        if outcome.poll():
            with contextlib.suppress(EOFError, OSError):
                payload = outcome.recv_bytes()
        process.join()
        exitcode = process.exitcode
        # Reaped: release its descriptors, as the handle may be held long after
        self._process = None
        process.close()
        if payload is None:
            if self.token.is_set():
                raise StoppedError()
            raise ProcessExitError(self.id, exitcode)
        # The child's report is the outcome, recorded as reported: raised, it
        # would be read against this task's token (_raised()), which can
        # differ from the child's
        result, error, stopped = self._decode(payload)
        if stopped:
            self.stopped = True
        elif error is not None:
            self.exception, self.exception_tb = error, error.__traceback__
        return result

    def _decode(self, payload: bytes) -> tuple[Any, BaseException | None, bool]:
        """The child's report: its result, its error, and whether it was
        stopped.

        Raises:
            RuntimeError: If it does not unpickle here, though it did in the
                child: a class only the child can import.
        """
        try:
            report: tuple[Any, BaseException | None, bool] = pickle.loads(payload)
        except Exception as e:
            raise RuntimeError(
                f"task {self.id}'s outcome could not be unpickled here: {e!r}"
            ) from e
        return report

    def terminate(self) -> None:
        """Send the child SIGTERM, if it is running."""
        self._send(lambda process: process.terminate())

    def kill(self) -> None:
        """Send the child SIGKILL, if it is running."""
        self._send(lambda process: process.kill())

    def _send(self, signal: Callable[[BaseProcess], None]) -> None:
        """*signal* the child, if it is running. One reaped and closed while
        this ran (_outcome()) raises ValueError: nothing is left to signal."""
        process = self._process
        if process is not None:
            with contextlib.suppress(ValueError):
                if process.is_alive():
                    signal(process)


def _opened(
    ends: contextlib.ExitStack, pair: tuple[Connection, Connection]
) -> tuple[Connection, Connection]:
    """*pair*, each end closed when *ends* exits."""
    for end in pair:
        ends.callback(end.close)
    return pair


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
    outcome; its token stops on a signal or EOF on *stop*. A signal sent
    before the child started is read here, before the call, not left to the
    listener thread to win the race against it: the runtime's stop signals a
    child before it forces it, so a child its stop forced before it was
    started skips the call."""
    token = StopToken()
    if stop.poll(0):  # a signal, or EOF: the parent is gone
        token.stop()
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
    here; else a RuntimeError naming why, in place of its result and error.
    An error carries its traceback in the child as a note."""
    error = task.exception
    note = None
    if error is not None:
        trace = "".join(traceback.format_exception(error))
        note = f"Traceback in the process of task {task.id}:\n{trace}"
        error.add_note(note)
    try:
        payload = pickle.dumps((task.result, error, task.stopped))
        pickle.loads(payload)
    except Exception as e:
        failure = RuntimeError(f"task {task.id} ended unpicklable: {e!r}")
        if note is not None:
            failure.add_note(note)
        payload = pickle.dumps((None, failure, False))
    outcome.send_bytes(payload)
