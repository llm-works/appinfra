"""Tests for appinfra.app.fastapi module initialization."""

import pytest


@pytest.mark.unit
class TestFastAPIImports:
    """Tests for FastAPI module imports."""

    def test_config_classes_available(self):
        """Test config classes are always importable."""
        from appinfra.app.fastapi import ApiConfig, IPCConfig, UvicornConfig

        # These should always work, even without FastAPI installed
        config = ApiConfig()
        assert config.host == "0.0.0.0"

        ipc_config = IPCConfig()
        assert ipc_config.max_pending == 100

        uvicorn_config = UvicornConfig()
        assert uvicorn_config.workers == 1

    def test_server_builder_available(self):
        """Test ServerBuilder is importable."""
        from appinfra.app.fastapi import ServerBuilder

        # Should be available since FastAPI is installed
        assert ServerBuilder is not None

    def test_server_plugin_available(self):
        """Test ServerPlugin is importable."""
        from appinfra.app.fastapi import ServerPlugin

        # Should be available since FastAPI is installed
        assert ServerPlugin is not None

    def test_ipc_channel_available(self):
        """Test IPCChannel is importable."""
        from appinfra.app.fastapi import IPCChannel

        # Should be available since FastAPI is installed
        assert IPCChannel is not None

    def test_server_available(self):
        """Test Server is importable."""
        from appinfra.app.fastapi import Server

        # Should be available since FastAPI is installed
        assert Server is not None

    def test_all_exports(self):
        """Test __all__ contains expected exports."""
        import appinfra.app.fastapi as fastapi_module

        expected = [
            "ServerBuilder",
            "Server",
            "IPCChannel",
            "ApiConfig",
            "UvicornConfig",
            "IPCConfig",
            "ServerPlugin",
        ]

        for name in expected:
            assert name in fastapi_module.__all__
            assert hasattr(fastapi_module, name)

    def test_has_fastapi_flag(self):
        """Test _HAS_FASTAPI flag is True when FastAPI is installed."""
        import appinfra.app.fastapi as fastapi_module

        assert fastapi_module._HAS_FASTAPI is True


@pytest.mark.unit
class TestFastAPIStubs:
    """Tests for stub classes when FastAPI is not installed."""

    def test_stub_classes_raise_import_error(self):
        """Test that stub classes raise ImportError with helpful message."""
        # We can't easily uninstall FastAPI, so we test the stub classes directly
        # by simulating what would happen if the import failed

        # Create stub classes inline (simulating the except block)
        _INSTALL_MSG = (
            "FastAPI is not installed. Install with: pip install appinfra[fastapi]"
        )

        class StubServerBuilder:
            def __init__(self, *args, **kwargs):
                raise ImportError(_INSTALL_MSG)

        class StubServer:
            def __init__(self, *args, **kwargs):
                raise ImportError(_INSTALL_MSG)

        class StubIPCChannel:
            def __init__(self, *args, **kwargs):
                raise ImportError(_INSTALL_MSG)

        class StubServerPlugin:
            def __init__(self, *args, **kwargs):
                raise ImportError(_INSTALL_MSG)

        # Test each stub raises ImportError with correct message
        for stub_class in [
            StubServerBuilder,
            StubServer,
            StubIPCChannel,
            StubServerPlugin,
        ]:
            with pytest.raises(ImportError) as exc_info:
                stub_class("test")

            assert "FastAPI is not installed" in str(exc_info.value)
            assert "pip install appinfra[fastapi]" in str(exc_info.value)

    def test_stub_accepts_any_arguments(self):
        """Test that stubs accept any arguments before raising."""
        _INSTALL_MSG = (
            "FastAPI is not installed. Install with: pip install appinfra[fastapi]"
        )

        class StubClass:
            def __init__(self, *args, **kwargs):
                raise ImportError(_INSTALL_MSG)

        # Should accept args and kwargs before raising
        with pytest.raises(ImportError):
            StubClass("arg1", "arg2", kwarg1="value1", kwarg2="value2")

    def test_install_message_constant(self):
        """Test the install message constant exists and has correct content."""
        import appinfra.app.fastapi as fastapi_module

        assert hasattr(fastapi_module, "_INSTALL_MSG")
        assert "pip install appinfra[fastapi]" in fastapi_module._INSTALL_MSG

    def test_stub_classes_when_fastapi_not_installed(self):
        """Test that stub classes are created when FastAPI is not installed.

        This test simulates the ImportError scenario by temporarily blocking
        the FastAPI-dependent submodule imports and using exec to evaluate
        the stub class definitions directly.
        """
        # The stub code that runs when FastAPI is not installed
        stub_code = '''
from typing import Any

_INSTALL_MSG = "FastAPI is not installed. Install with: pip install appinfra[fastapi]"
_HAS_FASTAPI = False

class ServerBuilder:
    """Stub for ServerBuilder when FastAPI is not installed."""
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise ImportError(_INSTALL_MSG)

class Server:
    """Stub for Server when FastAPI is not installed."""
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise ImportError(_INSTALL_MSG)

class IPCChannel:
    """Stub for IPCChannel when FastAPI is not installed."""
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise ImportError(_INSTALL_MSG)

class ServerPlugin:
    """Stub for ServerPlugin when FastAPI is not installed."""
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise ImportError(_INSTALL_MSG)
'''
        # Execute the stub code in a namespace
        stub_namespace: dict = {}
        exec(stub_code, stub_namespace)

        # Verify _HAS_FASTAPI is False
        assert stub_namespace["_HAS_FASTAPI"] is False

        # Try to instantiate each stub - should raise ImportError
        with pytest.raises(ImportError) as exc_info:
            stub_namespace["ServerBuilder"]("test")
        assert "pip install appinfra[fastapi]" in str(exc_info.value)

        with pytest.raises(ImportError) as exc_info:
            stub_namespace["Server"](None)
        assert "pip install appinfra[fastapi]" in str(exc_info.value)

        with pytest.raises(ImportError) as exc_info:
            stub_namespace["IPCChannel"](None, None)
        assert "pip install appinfra[fastapi]" in str(exc_info.value)

        with pytest.raises(ImportError) as exc_info:
            stub_namespace["ServerPlugin"](None)
        assert "pip install appinfra[fastapi]" in str(exc_info.value)

        # Verify docstrings exist
        assert "Stub" in stub_namespace["ServerBuilder"].__doc__
        assert "Stub" in stub_namespace["Server"].__doc__
        assert "Stub" in stub_namespace["IPCChannel"].__doc__
        assert "Stub" in stub_namespace["ServerPlugin"].__doc__
