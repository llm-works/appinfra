# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""uvicorn server that exits when its parent process dies or asks it to stop."""

from __future__ import annotations

import multiprocessing as mp
import socket
from ctypes import c_int
from multiprocessing.connection import wait
from multiprocessing.synchronize import Event as MPEvent
from typing import Any

import uvicorn

from .ipc import IPCChannel


class WatchedServer(uvicorn.Server):
    """uvicorn Server that stops on parent death or a set shutdown event.

    uvicorn calls ``on_tick()`` from its main loop every 0.1s. Each tick checks,
    without blocking, whether the parent's process sentinel is readable (the
    parent exited, including by SIGKILL) or the shutdown event is set. On
    either, the IPC channel is closed first: uvicorn drains in-flight requests
    before the lifespan shutdown would close it, so requests waiting for a
    reply from a dead parent would otherwise hold the process for up to the
    response timeout. Closing it makes them fail with ``ChannelClosedError``
    right away, then the main loop exits into uvicorn's normal shutdown.

    The parent is ``mp.parent_process()``, not ``os.getppid()``: under the
    forkserver start method the OS parent is the fork server.

    Once uvicorn has started, the port it bound goes to ``bound_port``, shared with
    the parent, and only then is ``ready`` set: with port 0 the OS picks the port, and
    the parent reads it as soon as the server counts as up.
    """

    should_exit: bool  # inherited from uvicorn.Server, declared for mypy
    started: bool  # inherited from uvicorn.Server, declared for mypy
    servers: list[Any]  # inherited from uvicorn.Server, declared for mypy

    def __init__(
        self,
        config: uvicorn.Config,
        shutdown_event: MPEvent,
        ipc_channel: IPCChannel | None,
        bound_port: c_int,
    ) -> None:
        super().__init__(config)
        self._shutdown_event = shutdown_event
        self._ipc_channel = ipc_channel
        self._bound_port = bound_port
        self.ready = False
        parent = mp.parent_process()
        self._parent_sentinel = parent.sentinel if parent is not None else None

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        """Start uvicorn, then publish the port it bound and mark the server ready."""
        await super().startup(sockets=sockets)
        if self.started:
            self._bound_port.value = self.servers[0].sockets[0].getsockname()[1]
            self.ready = True

    async def on_tick(self, counter: int) -> bool:
        """Start shutdown once the parent is gone or shutdown was requested."""
        if not self.should_exit and self._exit_requested():
            self.should_exit = True
            if self._ipc_channel is not None:
                await self._ipc_channel.stop_polling()
        result: bool = await super().on_tick(counter)
        return result

    def _exit_requested(self) -> bool:
        if self._shutdown_event.is_set():
            return True
        if self._parent_sentinel is None:
            return False
        return bool(wait([self._parent_sentinel], timeout=0))
