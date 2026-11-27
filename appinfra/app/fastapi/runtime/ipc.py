# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The FastAPI subprocess's side of its IPC with the parent.

Requests go to the parent on server.requests, a process Chan homed there;
each carries the Chan its reply comes back on, made here. IPCChannel adds
what the routes need on top: a bound on the requests in flight, the health
it reports, and the configured response timeout.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from ....runtime import Chan
from ....runtime.chan import ClosedError
from ..config.ipc import IPCConfig

#: What server.requests carries: a request, and the Chan its reply comes back on
Request = tuple[Any, Chan[Any]]


class IPCChannel:
    """
    Request/reply from the FastAPI subprocess to the parent.

    The parent answers each request on the reply Chan it came with: one
    value for submit(), any number for stream(), which ends when the parent
    closes the reply Chan. A reply Chan is closed here once its route stops
    waiting (answered, timed out or gone), so a parent sending to it after
    that gets ClosedError rather than a value nobody reads.

    Example usage in FastAPI handler:
        async def inference(request: InferenceRequest, ipc: IPCChannel = Depends(get_ipc)):
            return await ipc.submit(request.data, timeout=60.0)
    """

    def __init__(self, requests: Chan[Request], config: IPCConfig) -> None:
        """
        Initialize IPC channel.

        Args:
            requests: The parent's requests Chan, as this process holds it
            config: IPC configuration
        """
        self._requests = requests
        self._config = config
        self._pending_count = 0

    @property
    def pending_count(self) -> int:
        """Number of requests currently awaiting a reply."""
        return self._pending_count

    @property
    def health_status(self) -> dict[str, Any]:
        """
        Health status for reporting.

        Returns dict with:
        - pending_requests: Current number of pending requests
        - max_pending: Configured maximum
        - is_healthy: True if under capacity
        """
        return {
            "pending_requests": self._pending_count,
            "max_pending": self._config.max_pending,
            "is_healthy": self._pending_count < self._config.max_pending,
        }

    async def submit(self, request: Any, timeout: float | None = None) -> Any:
        """
        Send *request* to the parent and wait for its reply.

        Args:
            request: Any value that pickles
            timeout: Seconds for the whole exchange (None = the configured
                response timeout)

        Returns:
            The parent's reply

        Raises:
            RuntimeError: If max_pending requests are already in flight
            TimeoutError: If no reply came within *timeout*
            ClosedError: If the parent closed its requests Chan, or the reply
                Chan without a reply
        """
        self._admit()
        reply: Chan[Any] = Chan(1, process=True)
        try:
            deadline = time.monotonic() + self._timeout(timeout)
            await self._requests.asend((request, reply), timeout=_left(deadline))
            return await reply.arecv(timeout=_left(deadline))
        finally:
            reply.close()
            self._pending_count -= 1

    async def stream(
        self, request: Any, timeout: float | None = None
    ) -> AsyncIterator[Any]:
        """
        Send *request* to the parent and yield each value it replies with,
        until it closes the reply Chan.

        Args:
            request: Any value that pickles
            timeout: Seconds for the request to go out, and for each value
                (None = the configured response timeout)

        Yields:
            The parent's reply values, in order

        Raises:
            RuntimeError: If max_pending requests are already in flight
            TimeoutError: If a value did not come within *timeout*
            ClosedError: If the parent closed its requests Chan
        """
        self._admit()
        reply: Chan[Any] = Chan(1, process=True)
        try:
            wait = self._timeout(timeout)
            await self._requests.asend((request, reply), timeout=wait)
            while True:
                try:
                    value = await reply.arecv(timeout=wait)
                except ClosedError:
                    return
                yield value
        finally:
            reply.close()
            self._pending_count -= 1

    def _admit(self) -> None:
        """Count one more request in flight, or refuse it over max_pending."""
        if self._pending_count >= self._config.max_pending:
            raise RuntimeError(
                f"Max pending requests exceeded ({self._config.max_pending})"
            )
        self._pending_count += 1

    def _timeout(self, timeout: float | None) -> float:
        return self._config.response_timeout if timeout is None else timeout


def _left(deadline: float) -> float:
    """Seconds left until *deadline*; 0 once it has passed (do not wait)."""
    return max(0.0, deadline - time.monotonic())
