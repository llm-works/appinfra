"""
Integration test for FastAPI IPC + lifecycle callbacks.

This test validates the fix for a bug where using with_on_startup() with
subprocess mode (.subprocess.with_ipc()) caused the response queue to stop
delivering messages. The root cause was that FastAPI ignores on_event()
handlers when a lifespan is present, so IPC polling never started.

The fix integrates IPC lifecycle (start_polling/stop_polling) directly into
the adapter's lifespan context manager instead of using deprecated on_event().
"""

import importlib
import multiprocessing as mp
import threading
import time
from dataclasses import dataclass
from queue import Empty

import pytest
import requests


def _get_real_fastapi():
    """Get the real fastapi package, avoiding test directory shadowing."""
    import sys

    # Temporarily remove test paths that might shadow fastapi
    original_path = sys.path.copy()
    sys.path = [p for p in sys.path if "tests/infra/app" not in p]
    try:
        # Force reimport
        if "fastapi" in sys.modules:
            del sys.modules["fastapi"]
        return importlib.import_module("fastapi")
    finally:
        sys.path = original_path


# Skip entire module if FastAPI is shadowed (happens in xdist workers)
def _check_module_requirements():
    """Check requirements at module load time."""
    try:
        # This import might fail if fastapi is shadowed
        from appinfra.app.fastapi.runtime.adapter import FASTAPI_AVAILABLE

        return FASTAPI_AVAILABLE
    except ImportError:
        return False


# Module-level skip if requirements not met
if not _check_module_requirements():
    pytest.skip("FastAPI not available (may be shadowed)", allow_module_level=True)


@dataclass
class IPCRequest:
    """Test request message for IPC."""

    id: str
    data: str


@dataclass
class IPCResponse:
    """Test response message for IPC."""

    id: str
    result: str
    error: str | None = None


# Exception and handler for subprocess exception handler test
# Must be at module level to be picklable
class _TestSubprocessError(Exception):
    """Test exception for subprocess handler test."""

    pass


from appinfra.app.fastapi.handlers import ExceptionHandler


class _TestSubprocessErrorHandler(ExceptionHandler):
    """Handler that uses Logger - tests Logger injection in subprocess."""

    async def handle(self, request, exc: _TestSubprocessError):
        from starlette.responses import JSONResponse

        # This will fail if Logger wasn't injected
        self._lg.warning("test exception handled", extra={"error": str(exc)})
        return JSONResponse(
            {"error": "handled", "message": str(exc)},
            status_code=418,  # I'm a teapot - distinctive status code
        )


def _ipc_request_handler(
    request_q: mp.Queue, response_q: mp.Queue, stop_event: threading.Event
) -> None:
    """
    Simulates main process handling IPC requests.

    Reads requests from request_q, processes them, and puts responses in response_q.
    """
    while not stop_event.is_set():
        try:
            request = request_q.get(timeout=0.1)
            # Echo the data back as response
            response = IPCResponse(
                id=request.id,
                result=f"processed:{request.data}",
            )
            response_q.put(response)
        except Empty:
            continue
        except Exception:
            break


@pytest.mark.integration
class TestFastAPIIPCWithLifecycleCallbacks:
    """Integration tests for IPC + lifecycle callback interaction."""

    @pytest.fixture(autouse=True)
    def check_fastapi_installed(self):
        """Skip tests if FastAPI is not installed or shadowed by test package."""
        try:
            # Check if appinfra can import FastAPI (it may be shadowed in xdist)
            from appinfra.app.fastapi.runtime.adapter import FASTAPI_AVAILABLE

            if not FASTAPI_AVAILABLE:
                pytest.skip("FastAPI not available in appinfra")

            fastapi = _get_real_fastapi()
            if not hasattr(fastapi, "FastAPI"):
                pytest.skip("Real FastAPI package not available")
        except ImportError as e:
            pytest.skip(f"FastAPI import failed: {e}")

    def test_ipc_works_with_startup_callback(self):
        """
        Test that IPC responses are delivered when startup callbacks are registered.

        This is a regression test for the bug where with_on_startup() broke IPC
        because FastAPI's on_event() handlers are ignored when a lifespan is present.
        """
        from appinfra.app.fastapi.builder.server import ServerBuilder

        # Create IPC queues
        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()

        # Track startup callback execution
        startup_called = mp.Value("b", False)

        async def track_startup(app):
            """Startup callback that tracks its execution."""
            startup_called.value = True

        # Build server with startup callback AND IPC mode
        # This combination previously broke IPC polling
        from appinfra.log import Logger

        lg = Logger("test-ipc-lifespan")
        server = (
            ServerBuilder(lg, "test-ipc-lifespan")
            .with_host("127.0.0.1")
            .with_port(18765)  # Use non-standard port to avoid conflicts
            .with_on_startup(track_startup, name="track_startup")
            .routes.with_route("/ping", lambda: {"status": "ok"}, methods=["GET"])
            .done()
            .subprocess.with_ipc(request_q, response_q)
            .done()
            .build()
        )

        # Start the "main process" handler thread
        stop_event = threading.Event()
        handler_thread = threading.Thread(
            target=_ipc_request_handler,
            args=(request_q, response_q, stop_event),
            daemon=True,
        )
        handler_thread.start()

        try:
            # Start the subprocess
            server.start_subprocess()

            # Wait for server to be ready (poll the /ping endpoint)
            ready = False
            for _ in range(50):  # 5 second timeout
                try:
                    resp = requests.get("http://127.0.0.1:18765/ping", timeout=0.5)
                    if resp.status_code == 200:
                        ready = True
                        break
                except requests.exceptions.ConnectionError:
                    time.sleep(0.1)
                    continue

            assert ready, "Server did not become ready"
            assert startup_called.value, "Startup callback was not executed"

            # The server is running with startup callback executed
            # In a full test, we'd make an IPC request here
            # For now, we've proven that:
            # 1. Server starts with startup callback
            # 2. Startup callback executes
            # 3. Server accepts HTTP requests (meaning lifespan completed startup)

        finally:
            stop_event.set()
            server.stop(timeout=2.0)
            handler_thread.join(timeout=1.0)

    def test_ipc_polling_receives_responses_with_startup_callback(self):
        """
        Full integration test: verify IPC responses flow through with startup callbacks.

        This test creates a route that uses IPC, makes an HTTP request,
        and verifies the response comes back through the IPC channel.
        """
        import uuid

        from appinfra.app.fastapi.builder.server import ServerBuilder
        from appinfra.app.fastapi.runtime.ipc import IPCChannel

        # Get real fastapi to avoid test package shadowing
        fastapi = _get_real_fastapi()
        Depends = fastapi.Depends
        Request = fastapi.Request

        # Create IPC queues
        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()

        # Dependency to get IPC channel from app state
        def get_ipc(request: Request) -> IPCChannel:
            return request.app.state.ipc_channel

        # Route handler that uses IPC
        async def ipc_echo_handler(data: str, ipc: IPCChannel = Depends(get_ipc)):
            request_id = str(uuid.uuid4())
            ipc_request = IPCRequest(id=request_id, data=data)

            # This submit will:
            # 1. Put request in request_q
            # 2. Wait for response in response_q (via IPC polling)
            response = await ipc.submit(request_id, ipc_request, timeout=5.0)
            return {"result": response.result}

        # Startup callback - this is what triggered the bug
        async def startup_callback(app):
            app.state.startup_completed = True

        # Build server
        from appinfra.log import Logger

        lg = Logger("test-ipc-full")
        server = (
            ServerBuilder(lg, "test-ipc-full")
            .with_host("127.0.0.1")
            .with_port(18766)
            .with_on_startup(startup_callback, name="startup")
            .routes.with_route("/ping", lambda: {"status": "ok"}, methods=["GET"])
            .with_route("/echo/{data}", ipc_echo_handler, methods=["GET"])
            .done()
            .subprocess.with_ipc(request_q, response_q)
            .done()
            .build()
        )

        # Start the "main process" handler thread
        stop_event = threading.Event()
        handler_thread = threading.Thread(
            target=_ipc_request_handler,
            args=(request_q, response_q, stop_event),
            daemon=True,
        )
        handler_thread.start()

        try:
            # Start the subprocess
            server.start_subprocess()

            # Wait for server to be ready
            ready = False
            for _ in range(50):
                try:
                    resp = requests.get("http://127.0.0.1:18766/ping", timeout=0.5)
                    if resp.status_code == 200:
                        ready = True
                        break
                except requests.exceptions.ConnectionError:
                    time.sleep(0.1)
                    continue

            assert ready, "Server did not become ready"

            # Make IPC request - this is the critical test
            # If IPC polling isn't running, this will timeout
            resp = requests.get("http://127.0.0.1:18766/echo/testdata", timeout=5.0)

            assert resp.status_code == 200, (
                f"Expected 200, got {resp.status_code}: {resp.text}"
            )

            result = resp.json()
            assert result["result"] == "processed:testdata", (
                f"Unexpected result: {result}"
            )

        finally:
            stop_event.set()
            server.stop(timeout=2.0)
            handler_thread.join(timeout=1.0)

    def test_exception_handler_with_logger_in_subprocess(self):
        """
        Test that ExceptionHandler with Logger works correctly in subprocess mode.

        This tests the Logger injection feature where:
        1. Handler's Logger is stripped during pickle (subprocess spawn)
        2. Framework re-injects subprocess Logger after unpickling
        3. Handler can log and return proper responses
        """
        if _TestSubprocessErrorHandler is None:
            pytest.skip("ExceptionHandler not available")

        from appinfra.app.fastapi.builder.server import ServerBuilder
        from appinfra.log import Logger

        # Route that raises the exception
        async def raise_test_exception():
            raise _TestSubprocessError("test error message")

        # Create logger for the handler
        lg = Logger("test-handler")
        handler = _TestSubprocessErrorHandler(lg)

        # Create IPC queues (required for subprocess mode)
        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()

        # Build server with exception handler in subprocess mode
        from appinfra.log import Logger

        lg_server = Logger("test-exc-handler")
        server = (
            ServerBuilder(lg_server, "test-exc-handler")
            .with_host("127.0.0.1")
            .with_port(18767)
            .routes.with_route("/ping", lambda: {"status": "ok"}, methods=["GET"])
            .with_route("/raise", raise_test_exception, methods=["GET"])
            .with_exception_handler(_TestSubprocessError, handler)
            .done()
            .subprocess.with_ipc(request_q, response_q)
            .done()
            .build()
        )

        # No IPC handler needed - we're just testing exception handling
        try:
            # Start the subprocess
            server.start_subprocess()

            # Wait for server to be ready
            ready = False
            for _ in range(50):
                try:
                    resp = requests.get("http://127.0.0.1:18767/ping", timeout=0.5)
                    if resp.status_code == 200:
                        ready = True
                        break
                except requests.exceptions.ConnectionError:
                    time.sleep(0.1)
                    continue

            assert ready, "Server did not become ready"

            # Trigger the exception - this is the critical test
            # If Logger wasn't injected, the handler will raise RuntimeError
            resp = requests.get("http://127.0.0.1:18767/raise", timeout=5.0)

            # Verify the exception handler ran correctly
            assert resp.status_code == 418, (
                f"Expected 418 (teapot), got {resp.status_code}: {resp.text}"
            )

            result = resp.json()
            assert result["error"] == "handled", f"Unexpected result: {result}"
            assert result["message"] == "test error message", (
                f"Unexpected message: {result}"
            )

        finally:
            server.stop(timeout=2.0)
