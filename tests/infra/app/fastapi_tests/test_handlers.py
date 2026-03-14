"""Tests for exception handler subprocess support."""

from __future__ import annotations

import pickle
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from appinfra.app.fastapi.config.api import ApiConfig
from appinfra.app.fastapi.errors import ConfigError
from appinfra.app.fastapi.handlers import ExceptionHandler, LoggerInjectable
from appinfra.app.fastapi.runtime.adapter import (
    ExceptionHandlerDefinition,
    FastAPIAdapter,
)

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response


class ConcreteHandler(ExceptionHandler):
    """Concrete implementation of ExceptionHandler for testing."""

    async def handle(self, request: Request, exc: Exception) -> Response:
        from starlette.responses import JSONResponse

        self._lg.warning("handled exception", extra={"error": str(exc)})
        return JSONResponse({"error": str(exc)}, status_code=500)


class HandlerWithState(ExceptionHandler):
    """Handler with additional state for pickling tests."""

    def __init__(self, lg: object, extra_config: dict) -> None:
        super().__init__(lg)  # type: ignore[arg-type]
        self.extra_config = extra_config

    async def handle(self, request: Request, exc: Exception) -> Response:
        from starlette.responses import JSONResponse

        return JSONResponse({"error": str(exc)}, status_code=500)


class PicklableHandlerWithLoggerAttr:
    """Handler that can be pickled but has a Logger attribute (for warning test)."""

    def __init__(self) -> None:
        self.lg: object = None  # Will be set to a Logger

    def __call__(self, request: object, exc: Exception) -> None:
        pass


@pytest.mark.unit
class TestLoggerInjectableProtocol:
    """Tests for LoggerInjectable protocol."""

    def test_exception_handler_implements_protocol(self):
        """Test ExceptionHandler implements LoggerInjectable."""
        mock_lg = MagicMock()
        handler = ConcreteHandler(mock_lg)
        assert isinstance(handler, LoggerInjectable)

    def test_custom_class_with_set_logger_implements_protocol(self):
        """Test custom class with set_logger implements protocol."""

        class CustomHandler:
            def set_logger(self, lg):
                self._lg = lg

        handler = CustomHandler()
        assert isinstance(handler, LoggerInjectable)

    def test_class_without_set_logger_does_not_implement_protocol(self):
        """Test class without set_logger does not implement protocol."""

        class NoSetLogger:
            pass

        obj = NoSetLogger()
        assert not isinstance(obj, LoggerInjectable)


@pytest.mark.unit
class TestExceptionHandler:
    """Tests for ExceptionHandler base class."""

    def test_init_stores_logger(self):
        """Test __init__ stores the logger."""
        mock_lg = MagicMock()
        handler = ConcreteHandler(mock_lg)
        assert handler._lg is mock_lg

    def test_getstate_strips_logger(self):
        """Test __getstate__ sets logger to None for pickling."""
        mock_lg = MagicMock()
        handler = ConcreteHandler(mock_lg)

        state = handler.__getstate__()

        assert state["_lg"] is None

    def test_setstate_restores_state(self):
        """Test __setstate__ restores state from dict."""
        handler = ConcreteHandler.__new__(ConcreteHandler)
        state = {"_lg": None, "other_attr": "value"}

        handler.__setstate__(state)

        assert handler._lg is None
        assert handler.other_attr == "value"

    def test_set_logger_injects_logger(self):
        """Test set_logger injects the logger."""
        mock_lg = MagicMock()
        handler = ConcreteHandler.__new__(ConcreteHandler)
        handler._lg = None

        handler.set_logger(mock_lg)

        assert handler._lg is mock_lg


@pytest.mark.unit
class TestExceptionHandlerPickling:
    """Tests for ExceptionHandler pickling behavior."""

    def test_handler_can_be_pickled(self):
        """Test handler can be pickled."""
        mock_lg = MagicMock()
        handler = ConcreteHandler(mock_lg)

        pickled = pickle.dumps(handler)
        unpickled = pickle.loads(pickled)

        assert isinstance(unpickled, ConcreteHandler)
        assert unpickled._lg is None  # Logger stripped

    def test_pickled_handler_works_after_logger_injection(self):
        """Test pickled handler works after logger is re-injected."""
        mock_lg = MagicMock()
        handler = ConcreteHandler(mock_lg)

        # Pickle and unpickle
        pickled = pickle.dumps(handler)
        unpickled = pickle.loads(pickled)

        # Inject new logger
        new_lg = MagicMock()
        unpickled.set_logger(new_lg)

        assert unpickled._lg is new_lg

    def test_handler_with_additional_state_preserves_it(self):
        """Test handler preserves additional state during pickling."""
        mock_lg = MagicMock()
        handler = HandlerWithState(mock_lg, {"timeout": 30})

        pickled = pickle.dumps(handler)
        unpickled = pickle.loads(pickled)

        assert unpickled.extra_config == {"timeout": 30}
        assert unpickled._lg is None  # Logger still stripped


@pytest.mark.unit
class TestExceptionHandlerCall:
    """Tests for ExceptionHandler.__call__."""

    @pytest.mark.asyncio
    async def test_call_raises_without_logger(self):
        """Test __call__ raises RuntimeError if logger not injected."""
        handler = ConcreteHandler.__new__(ConcreteHandler)
        handler._lg = None

        mock_request = MagicMock()
        mock_exc = ValueError("test")

        with pytest.raises(RuntimeError, match="Logger not injected"):
            await handler(mock_request, mock_exc)

    @pytest.mark.asyncio
    async def test_call_delegates_to_handle(self):
        """Test __call__ delegates to handle() when logger is present."""

        class TestHandler(ExceptionHandler):
            def __init__(self, lg):
                super().__init__(lg)
                self.handled = False

            async def handle(self, request, exc):
                self.handled = True
                return MagicMock()

        mock_lg = MagicMock()
        handler = TestHandler(mock_lg)

        mock_request = MagicMock()
        mock_exc = ValueError("test")

        await handler(mock_request, mock_exc)

        assert handler.handled is True


@pytest.mark.unit
class TestFastAPIAdapterInjectSubprocessLogger:
    """Tests for FastAPIAdapter.inject_subprocess_logger."""

    @pytest.fixture
    def mock_fastapi(self):
        """Mock FastAPI module."""
        with (
            patch("appinfra.app.fastapi.runtime.adapter.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.adapter.FastAPI") as mock_fastapi,
            patch("appinfra.app.fastapi.runtime.adapter.CORSMiddleware"),
        ):
            mock_app = MagicMock()
            mock_fastapi.return_value = mock_app
            yield {"FastAPI": mock_fastapi, "app": mock_app}

    def test_injects_into_logger_injectable_handler(self, mock_fastapi):
        """Test inject_subprocess_logger injects logger into LoggerInjectable handlers."""
        adapter = FastAPIAdapter(ApiConfig())

        mock_lg = MagicMock()
        handler = ConcreteHandler(mock_lg)
        adapter.add_exception_handler(ExceptionHandlerDefinition(ValueError, handler))

        # Simulate subprocess scenario: logger is None after unpickling
        handler._lg = None

        new_lg = MagicMock()
        adapter.inject_subprocess_logger(new_lg)

        assert handler._lg is new_lg

    def test_ignores_non_injectable_handlers(self, mock_fastapi):
        """Test inject_subprocess_logger ignores handlers without LoggerInjectable."""
        adapter = FastAPIAdapter(ApiConfig())

        def plain_handler(request, exc):
            pass

        adapter.add_exception_handler(
            ExceptionHandlerDefinition(ValueError, plain_handler)
        )

        # Should not raise
        new_lg = MagicMock()
        adapter.inject_subprocess_logger(new_lg)

    def test_injects_into_multiple_handlers(self, mock_fastapi):
        """Test inject_subprocess_logger injects into multiple handlers."""
        adapter = FastAPIAdapter(ApiConfig())

        mock_lg = MagicMock()
        handler1 = ConcreteHandler(mock_lg)
        handler2 = ConcreteHandler(mock_lg)
        handler1._lg = None
        handler2._lg = None

        adapter.add_exception_handler(ExceptionHandlerDefinition(ValueError, handler1))
        adapter.add_exception_handler(ExceptionHandlerDefinition(TypeError, handler2))

        new_lg = MagicMock()
        adapter.inject_subprocess_logger(new_lg)

        assert handler1._lg is new_lg
        assert handler2._lg is new_lg


@pytest.mark.unit
class TestServerBuilderValidation:
    """Tests for ServerBuilder subprocess handler validation."""

    @pytest.fixture
    def mock_fastapi(self):
        """Mock FastAPI module."""
        with (
            patch("appinfra.app.fastapi.runtime.adapter.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.adapter.FastAPI") as mock_fastapi,
            patch("appinfra.app.fastapi.runtime.adapter.CORSMiddleware"),
        ):
            mock_app = MagicMock()
            mock_fastapi.return_value = mock_app
            yield {"FastAPI": mock_fastapi, "app": mock_app}

    def test_build_validates_in_subprocess_mode(self, mock_fastapi):
        """Test build() validates handlers when subprocess mode is enabled."""
        import multiprocessing as mp

        from appinfra.app.fastapi.builder.server import ServerBuilder

        # Create unpicklable handler (with a lambda that can't be pickled)
        class UnpicklableHandler:
            def __init__(self):
                self.callback = lambda x: x  # Lambdas can't be pickled

        handler = UnpicklableHandler()

        mock_lg = MagicMock()
        builder = ServerBuilder(mock_lg, "test")
        builder._exception_handlers.append(
            ExceptionHandlerDefinition(ValueError, handler)
        )
        builder._request_q = mp.Queue()
        builder._response_q = mp.Queue()

        with pytest.raises(ConfigError, match="cannot be pickled"):
            builder.build()

    def test_build_allows_picklable_handlers(self, mock_fastapi):
        """Test build() allows picklable handlers in subprocess mode."""
        import multiprocessing as mp

        from appinfra.app.fastapi.builder.server import ServerBuilder

        mock_lg = MagicMock()
        handler = ConcreteHandler(mock_lg)

        builder = ServerBuilder(mock_lg, "test")
        builder._exception_handlers.append(
            ExceptionHandlerDefinition(ValueError, handler)
        )
        builder._request_q = mp.Queue()
        builder._response_q = mp.Queue()

        # Should not raise
        server = builder.build()
        assert server is not None

    def test_build_skips_validation_without_subprocess(self, mock_fastapi):
        """Test build() skips validation when not in subprocess mode."""
        from appinfra.app.fastapi.builder.server import ServerBuilder

        # Create unpicklable handler
        class UnpicklableHandler:
            def __init__(self):
                self.callback = lambda x: x

        handler = UnpicklableHandler()

        mock_lg = MagicMock()
        builder = ServerBuilder(mock_lg, "test")
        builder._exception_handlers.append(
            ExceptionHandlerDefinition(ValueError, handler)
        )
        # No subprocess queues set

        # Should not raise (not in subprocess mode)
        server = builder.build()
        assert server is not None

    def test_warn_on_logger_attributes_function(self, mock_fastapi):
        """Test _warn_on_logger_attributes logs warning for Logger attributes."""
        from appinfra.app.fastapi.builder.server import ServerBuilder
        from appinfra.log import Logger

        # Use module-level class that can be pickled
        handler = PicklableHandlerWithLoggerAttr()
        handler.lg = Logger("test")  # Set a real Logger

        mock_lg = MagicMock()
        builder = ServerBuilder(mock_lg, "test")

        # Call the warning function directly (bypasses pickle check)
        builder._warn_on_logger_attributes(handler, "TestException")

        # Verify warning was logged via appinfra Logger
        mock_lg.warning.assert_called_once()
        call_args = mock_lg.warning.call_args
        assert "Logger attribute" in call_args[0][0]
        extra = call_args[1]["extra"]
        assert extra["handler"] == "PicklableHandlerWithLoggerAttr"
        assert extra["attribute"] == "lg"
        assert extra["exc_class"] == "TestException"
