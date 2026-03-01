"""Exception handler support for subprocess mode.

Provides base classes and protocols for exception handlers that work correctly
across process boundaries in subprocess mode. The main challenge is that Logger
instances cannot be pickled, so handlers that need logging must use these patterns.

Example:
    from appinfra.app.fastapi import ServerBuilder, ExceptionHandler
    from appinfra.log import Logger
    from starlette.responses import JSONResponse

    class TimeoutHandler(ExceptionHandler):
        async def handle(self, request, exc: TimeoutError):
            self._lg.warning("timeout", extra={"path": str(request.url.path)})
            return JSONResponse({"error": "timeout"}, status_code=504)

    lg = Logger("api")
    server = (ServerBuilder("api", lg=lg)
        .routes
        .with_exception_handler(TimeoutError, TimeoutHandler(lg))
        .done()
        .subprocess.with_ipc(req_q, resp_q).done()
        .build())
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

    from ...log import Logger


@runtime_checkable
class LoggerInjectable(Protocol):
    """Protocol for objects that need Logger injection after unpickling.

    Implement this protocol to allow the framework to inject a Logger instance
    after the object has been pickled and unpickled in subprocess mode.

    The framework will:
    1. Pickle the handler (with Logger stripped via __getstate__)
    2. Unpickle in subprocess (Logger is None)
    3. Call set_logger() with the subprocess's Logger instance
    """

    def set_logger(self, lg: Logger) -> None:
        """Inject the subprocess Logger after unpickling.

        Args:
            lg: The Logger instance created in the subprocess.
        """
        ...


class ExceptionHandler:
    """Base class for exception handlers that work across process boundaries.

    Logger is stripped during pickle and reinjected by the framework in subprocess
    mode. Subclasses implement the handle() method to process exceptions.

    Example:
        class MyHandler(ExceptionHandler):
            async def handle(self, request: Request, exc: Exception) -> Response:
                self._lg.error("error occurred", extra={"path": str(request.url.path)})
                return JSONResponse({"error": str(exc)}, status_code=500)
    """

    def __init__(self, lg: Logger) -> None:
        """Initialize handler with logger.

        Args:
            lg: Logger instance. Will be stripped during pickle and reinjected
                by the framework in subprocess mode.
        """
        self._lg: Logger | None = lg

    def __getstate__(self) -> dict[str, Any]:
        """Strip Logger from pickle state."""
        state = self.__dict__.copy()
        state["_lg"] = None
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Restore state after unpickling."""
        self.__dict__.update(state)

    def set_logger(self, lg: Logger) -> None:
        """Inject subprocess Logger after unpickling.

        Called by the framework in subprocess mode after the adapter is unpickled.

        Args:
            lg: The subprocess Logger instance.
        """
        self._lg = lg

    async def __call__(self, request: Request, exc: Exception) -> Response:
        """Handle the exception (called by FastAPI).

        Validates that Logger has been injected, then delegates to handle().

        Args:
            request: The incoming request.
            exc: The exception that was raised.

        Returns:
            Response to send to the client.

        Raises:
            RuntimeError: If Logger was not injected (framework error).
        """
        if self._lg is None:
            raise RuntimeError(
                "Logger not injected - ExceptionHandler used in subprocess mode without "
                "Logger injection. This is a framework error."
            )
        return await self.handle(request, exc)

    @abstractmethod
    async def handle(self, request: Request, exc: Exception) -> Response:
        """Handle the exception.

        Implement this method to process exceptions and return appropriate responses.

        Args:
            request: The incoming request.
            exc: The exception that was raised.

        Returns:
            Response to send to the client.
        """
        raise NotImplementedError
