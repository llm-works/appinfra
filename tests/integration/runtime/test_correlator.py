# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Correlator between threads: callers submit while a poll thread, owning the
transport, delivers what arrives."""

import threading
from dataclasses import dataclass

from appinfra.runtime import Chan, ChanClosedError, Correlator

CALLERS = 8


@dataclass(frozen=True)
class Msg:
    id: str
    body: int = 0


def _correlator(wire: Chan[Msg]) -> Correlator[Msg]:
    return Correlator(
        lambda m, timeout: wire.send(m, timeout),
        key=lambda m: m.id,
        failed=lambda m: False,
        final=lambda m: True,
    )


def _poll(wire: Chan[Msg], c: Correlator[Msg]) -> None:
    """The peer and its poll thread: takes every caller's request, then
    answers them last to first, a request of its own ahead of the answers."""
    requests = [wire.recv(timeout=10.0) for _ in range(CALLERS)]
    c.deliver(Msg("peer", -1))
    for request in reversed(requests):
        c.deliver(Msg(request.id, request.body * 2))


def test_concurrent_submits_each_get_their_own_reply() -> None:
    wire: Chan[Msg] = Chan(None)
    c = _correlator(wire)
    replies: dict[int, int] = {}

    def caller(n: int) -> None:
        replies[n] = c.submit(Msg(str(n), n), timeout=10.0).body

    callers = [threading.Thread(target=caller, args=(n,)) for n in range(CALLERS)]
    poller = threading.Thread(target=_poll, args=(wire, c))
    for thread in [poller, *callers]:
        thread.start()
    for thread in [poller, *callers]:
        thread.join(timeout=10.0)
    assert replies == {n: n * 2 for n in range(CALLERS)}
    assert c.recv(timeout=0) == Msg("peer", -1)


def test_a_close_from_another_thread_ends_a_waiting_submit() -> None:
    wire: Chan[Msg] = Chan(None)
    c = _correlator(wire)
    failed: list[BaseException] = []

    def caller() -> None:
        try:
            c.submit(Msg("a"), timeout=10.0)
        except ChanClosedError as e:
            failed.append(e)

    thread = threading.Thread(target=caller)
    thread.start()
    wire.recv(timeout=10.0)  # the request is out: the submit waits
    c.close()
    thread.join(timeout=10.0)
    assert len(failed) == 1
