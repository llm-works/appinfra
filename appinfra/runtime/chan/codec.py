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

Each ("h", id) is a handing over the home counts (Home.register()), and the
side that decodes it counts the ones it received, per proxy: once that proxy
is gone, a Release of that many lets the home drop the Chan. An encoding
that fails hands nothing over: what it registered is counted back.

Release races no reference to the same Chan: a value holds its proxies until
its frame is posted, frames go out in the order posted (one outbox per
endpoint), and the other side decodes each frame on its reader, in the order
they come, before it reads the Release behind them."""

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
    the proxies it makes, its home, for the Chans it hands across, and the
    release of a proxy gone."""

    home: Home

    def release(self, object_id: int, count: int) -> None:
        """Post a Release of *count* handings over of *object_id*. Called by
        a finalizer, at any point of any thread: it must take no lock."""


class _Imported:
    """The handings over of one object one proxy received, for its Release."""

    __slots__ = ("count",)

    def __init__(self) -> None:
        """One handing over, the proxy's first."""
        self.count = 1


class LinkCodec(Codec):
    """The codec of one endpoint, *side*: references for the process Chans
    in its payloads, both ways."""

    def __init__(self, side: Side) -> None:
        """The codec of *side*; its home is read as it encodes, so it may be
        made after the codec."""
        self._side = side
        self._lock = threading.Lock()  # guards _proxies and _imported
        # The proxy of each object while it lives, and what it received: an
        # entry made with its proxy, so one found with a live proxy is that
        # proxy's. Both drop their entries themselves as a proxy dies; the
        # proxy's finalizer touches neither, as it may run under this lock
        self._proxies: weakref.WeakValueDictionary[int, _ChanProxy[Any]] = (
            weakref.WeakValueDictionary()
        )
        self._imported: weakref.WeakKeyDictionary[_ChanProxy[Any], _Imported] = (
            weakref.WeakKeyDictionary()
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
        """The value *data* encodes, from the other side; each Chan homed
        there counted as a handing over its proxy received.

        Raises:
            ClosedError: If a Chan coming back is no longer held at its home.
            Exception: As pickle.loads().
        """
        return _Unpickler(io.BytesIO(data), self).load()

    def _proxy(self, object_id: int) -> _ChanProxy[Any]:
        """The proxy of the object *object_id* homed on the other side, one
        handing over more received: the same proxy while it lives, else a new
        one, whose finalizer releases what it received."""
        with self._lock:
            proxy = self._proxies.get(object_id)
            if proxy is not None:
                self._imported[proxy].count += 1
                return proxy
            proxy = _ChanProxy(self._side, object_id)
            imported = _Imported()
            self._proxies[object_id] = proxy
            self._imported[proxy] = imported
        finalizer = weakref.finalize(proxy, _release, self._side, object_id, imported)
        finalizer.atexit = False  # the link ends with the interpreter
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

    def __init__(self, file: io.BytesIO, codec: LinkCodec) -> None:
        """Unpickle *file* for *codec*."""
        super().__init__(file)
        self._codec = codec

    def persistent_load(self, pid: Any) -> Chan[Any]:
        """The Chan *pid* refers to.

        Raises:
            ClosedError: If a Chan homed here is no longer held.
            pickle.UnpicklingError: For a reference of no known kind.
        """
        kind, object_id = pid
        if kind == _HOMED:
            return self._codec._proxy(object_id)
        if kind == _BACK:
            return self._codec._homed(object_id)
        raise pickle.UnpicklingError(f"unknown Chan reference {pid!r}")


def _release(side: Side, object_id: int, imported: _Imported) -> None:
    """Finalizer of a proxy: release the handings over it received. Runs
    wherever the proxy is collected; Side.release() takes no lock."""
    side.release(object_id, imported.count)
