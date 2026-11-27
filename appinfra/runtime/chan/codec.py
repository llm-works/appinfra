# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The link codec: an endpoint's payloads, with the process Chans in them
crossing as references to their homes, so the side that decodes gets the
same Chan, not a copy.

A process Chan homed on the side that encodes crosses as ("h", id), its id
at that home, and arrives as a proxy of it: one proxy per id while it
lives. A proxy of this link crosses as ("b", id), going back to its home,
and arrives as the Chan itself. A proxy of another link would need relaying
through this process, and a local Chan cannot cross at all: both refused.

Each ("h", id) is a handing over the home counts (Home.register()). One that
never reaches a proxy, as an encoding that fails or a value given back
undecoded, is counted back here."""

from __future__ import annotations

import io
import pickle
import threading
import weakref
from typing import Any, Protocol

from .chan import _LOCAL_ONLY, Chan
from .errors import ClosedError
from .home import Home
from .link import Codec
from .proxy import Caller, _ChanProxy

_HOMED = "h"  # homed at the side that encoded it
_BACK = "b"  # going back to its home, the side that decodes it


class Side(Caller, Protocol):
    """This process's end of the link, as the codec uses it: its calls, for
    the proxies it makes, and its home, for the Chans it hands across."""

    home: Home


class LinkCodec(Codec):
    """The codec of one endpoint, *side*: references for the process Chans
    in its payloads, both ways."""

    def __init__(self, side: Side) -> None:
        """The codec of *side*; its home is read as it encodes, so it may be
        made after the codec."""
        self._side = side
        self._lock = threading.Lock()  # guards _proxies
        self._proxies: weakref.WeakValueDictionary[int, _ChanProxy[Any]] = (
            weakref.WeakValueDictionary()
        )

    def encode(self, value: Any) -> bytes:
        """*value* as bytes, its process Chans as references. An encoding that
        fails hands nothing over: the Chans it registered are counted back.

        Raises:
            TypeError: If *value* holds a local Chan, or a proxy of another link.
            Exception: As pickle.dumps(), for a value that cannot be encoded.
        """
        buffer = io.BytesIO()
        pickler = _Pickler(buffer, self)
        try:
            pickler.dump(value)
        except BaseException:
            for object_id in pickler.handed:
                self._side.home.release(object_id, 1)
            raise
        return buffer.getvalue()

    def decode(self, data: bytes) -> Any:
        """The value *data* encodes, from the other side.

        Raises:
            ClosedError: If a Chan coming back is no longer held at its home.
            Exception: As pickle.loads().
        """
        return _Unpickler(io.BytesIO(data), self, own=False).load()

    def decode_own(self, data: bytes) -> Any:
        """The value of bytes this side encoded, coming back to it (a Return):
        its ("h", id) are its own Chans, handings over that never reached a
        proxy, counted back; its ("b", id) are proxies again.

        Raises:
            As decode().
        """
        return _Unpickler(io.BytesIO(data), self, own=True).load()

    def _proxy(self, object_id: int) -> _ChanProxy[Any]:
        """The proxy of the object *object_id* homed on the other side: the
        same one while it lives."""
        with self._lock:
            proxy = self._proxies.get(object_id)
            if proxy is None:
                proxy = _ChanProxy(self._side, object_id)
                self._proxies[object_id] = proxy
            return proxy

    def _homed(self, object_id: int) -> Chan[Any]:
        """The Chan *object_id* homed here.

        Raises:
            ClosedError: If it is no longer held: released, or the link ended.
        """
        chan = self._side.home.exported(object_id)
        if chan is None:
            raise ClosedError("channel released or closed")
        return chan


class _Pickler(pickle.Pickler):
    """Keeps each Chan in the value as a reference, and the ids it handed
    over, to count them back if the encoding fails."""

    def __init__(self, file: io.BytesIO, codec: LinkCodec) -> None:
        """Pickle into *file* for *codec*."""
        super().__init__(file, pickle.HIGHEST_PROTOCOL)
        self._codec = codec
        self.handed: list[int] = []

    def persistent_id(self, obj: Any) -> tuple[str, int] | None:
        """A Chan's reference; None for anything else, pickled as usual.

        Raises:
            TypeError: For a local Chan, or a proxy of another link.
        """
        if not isinstance(obj, Chan):
            return None
        if isinstance(obj, _ChanProxy):
            if obj._endpoint is not self._codec._side:
                raise TypeError(
                    "a proxy crosses a link only back to its Chan's home, not on "
                    "to a third process"
                )
            return (_BACK, obj._object_id)
        if not obj._process:
            raise TypeError(_LOCAL_ONLY)
        object_id = self._codec._side.home.register(obj)
        self.handed.append(object_id)
        return (_HOMED, object_id)


class _Unpickler(pickle.Unpickler):
    """Resolves each reference to its Chan: a proxy, or the Chan itself."""

    def __init__(self, file: io.BytesIO, codec: LinkCodec, *, own: bool) -> None:
        """Unpickle *file* for *codec*; *own*: bytes this side encoded."""
        super().__init__(file)
        self._codec = codec
        self._own = own

    def persistent_load(self, pid: Any) -> Chan[Any]:
        """The Chan *pid* refers to.

        Raises:
            ClosedError: If a Chan homed here is no longer held.
            pickle.UnpicklingError: For a reference of no known kind.
        """
        kind, object_id = pid
        if kind not in (_HOMED, _BACK):
            raise pickle.UnpicklingError(f"unknown Chan reference {pid!r}")
        # From the other side, "b" is homed here; in this side's own bytes, "h"
        homed_here = (kind == _BACK) != self._own
        if not homed_here:
            return self._codec._proxy(object_id)
        chan = self._codec._homed(object_id)
        if self._own:  # handed over in a Result that never reached a proxy
            self._codec._side.home.release(object_id, 1)
        return chan
