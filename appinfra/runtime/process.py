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
from typing import Any, Final

from .errors import ProcessExitError, StoppedError
from .stop import StopToken
from .task import ProcessDetail, TaskKind, _label, _Task
from .thread import _ThreadTask

# How every child starts: a fresh interpreter. Forking a process that runs the
# runtime's loop and threads is unsafe
START_METHOD: Final = "spawn"

# What terminate() and kill() ask of a child, the stronger one winning
_TERMINATE, _KILL = 1, 2

# Seconds a child forced to end gets after SIGTERM, and then after SIGKILL:
# on top of the timeout of the stop that forces it
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
    connection: the result, the exception with the child's traceback as a
    note (PEP 678), which, unlike a cause, survives any later pickling, as a
    done pipe's, or the stop. A child that exits without one fails the task with
    ProcessExitError, unless the task was stopped.
    """

    __slots__ = ("_process", "_lock", "_forced", "_ended")

    killable = True

    kind = TaskKind.PROCESS

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
        # The child, once started. Under _lock: terminate() and kill() record
        # what they were asked in _forced and signal it, so a force between
        # the child's start and its publication is not lost; and _release()
        # closes it, never in the middle of a signal
        self._process: BaseProcess | None = None
        self._lock = threading.Lock()
        self._forced = 0  # _TERMINATE or _KILL once forced
        # The reaped child, as it ended: a closed Process answers nothing
        self._ended: ProcessDetail | None = None

    def _call(self, fn: Callable[..., Any], args: tuple[Any, ...]) -> Any:
        """Run *fn*(*args*) in a child and return or raise its outcome."""
        ctx = mp.get_context(START_METHOD)
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
            self._publish(process)
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
        self._release(process)
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
        """Send the child SIGTERM, if it is running, or once it is published."""
        self._force(_TERMINATE)

    def kill(self) -> None:
        """Send the child SIGKILL, if it is running, or once it is published."""
        self._force(_KILL)

    def _force(self, level: int) -> None:
        """Record *level*, so a child not yet published gets it as it is
        (_publish()), and send it to one that is."""
        with self._lock:
            self._forced = max(self._forced, level)
            _send(self._process, level)

    def _publish(self, process: BaseProcess) -> None:
        """Make the started *process* the one terminate() and kill() reach,
        and send it what they were asked before: the stop that forced this
        task may have come between its start and here."""
        with self._lock:
            self._process = process
            _send(process, self._forced)

    def _release(self, process: BaseProcess) -> None:
        """Forget the reaped *process* and close it, releasing its descriptors,
        as the handle may be held long after. Under the lock that signals take
        too: Process.close() clears its handle before it marks itself closed,
        so a signal sent across a close fails with AttributeError."""
        with self._lock:
            self._ended = ProcessDetail(process.pid, process.exitcode, alive=False)
            self._process = None
            process.close()

    def grace(self) -> float:
        """Seconds past a stop's timeout by which a forced child has been
        terminated, killed _GRACE later, and given _GRACE more to be reaped.
        Read on each call, so a test can shorten _GRACE."""
        return 2 * _GRACE

    def process_detail(self) -> ProcessDetail:
        """The child as it is now: running, or ended and not yet reaped; as
        it ended once reaped; no pid before it has started."""
        with self._lock:
            if self._ended is not None:
                return self._ended
            process = self._process
            if process is None:
                return ProcessDetail(pid=None, exitcode=None, alive=False)
            # One poll of the child: a second could see it end after the first
            # did not. Published only once started, so no exit code means alive
            exitcode = process.exitcode
            return ProcessDetail(process.pid, exitcode, alive=exitcode is None)


def _send(process: BaseProcess | None, level: int) -> None:
    """Send *process* SIGKILL for _KILL, SIGTERM for _TERMINATE, if it is
    running; nothing for no process or no level. Called under the task's
    lock, which _release() closes the process under: a closed one is never
    signalled. ValueError, a closed process's, is suppressed all the same."""
    if process is None or not level:
        return
    with contextlib.suppress(ValueError):
        if process.is_alive():
            if level >= _KILL:
                process.kill()
            else:
                process.terminate()


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
