# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for logger factory.

Tests key functionality including:
- create_root method
- Logger already exists branch
- create_child method
- derive method
- Hot-reload of location via holder
"""

import collections
import io
import logging

import pytest

from appinfra.log import Logger
from appinfra.log.builder import LoggingBuilder
from appinfra.log.config import LogConfig
from appinfra.log.config_holder import LogConfigHolder
from appinfra.log.errors import LogConfigError, LoggerExistsError, LoggerNotFoundError
from appinfra.log.factory import LoggerFactory

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def log_config():
    """Create basic log configuration."""
    return LogConfig(level=logging.DEBUG, location=0, micros=False, colors=False)


@pytest.fixture
def unique_logger_name():
    """Generate unique logger name to avoid collisions."""
    import uuid

    return f"test_logger_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def cleanup_loggers():
    """Clean up loggers after each test."""
    yield
    # Clean up any test loggers created
    to_remove = [
        name
        for name in logging.root.manager.loggerDict
        if name.startswith("test_") or name.startswith("/")
    ]
    for name in to_remove:
        if name in logging.root.manager.loggerDict:
            lg = logging.getLogger(name)
            lg.handlers.clear()


# =============================================================================
# Test create_root method - Line 35
# =============================================================================


@pytest.mark.unit
class TestCreateRoot:
    """Test create_root method."""

    def test_create_root_basic(self, log_config):
        """Test create_root creates root logger (line 35)."""
        logger = LoggerFactory.create_root(log_config)

        assert logger is not None
        assert logger.name == "/"

        # Cleanup
        logger.handlers.clear()

    def test_create_root_with_extra(self, log_config):
        """create_root forwards pre-populated extra fields to the logger."""
        logger = LoggerFactory.create_root(log_config, extra={"service": "api"})

        assert logger._extra == {"service": "api"}

        # Cleanup
        logger.handlers.clear()

    def test_create_root_again_raises(self, log_config):
        """A second root setup is a name conflict, whatever its config."""
        first = LoggerFactory.create_root(log_config, extra={"service": "api"})

        with pytest.raises(LoggerExistsError):
            LoggerFactory.create_root(log_config, extra={"service": "worker"})

        assert first._extra == {"service": "api"}  # the first logger is untouched


# =============================================================================
# Existing names: create raises
# =============================================================================


@pytest.mark.unit
class TestLoggerExists:
    """create() never touches an existing logger."""

    def test_create_raises_when_name_exists(self, log_config, unique_logger_name):
        """Same or different config: the second create raises."""
        first = LoggerFactory.create(unique_logger_name, log_config)

        with pytest.raises(LoggerExistsError) as exc:
            LoggerFactory.create(unique_logger_name, log_config)

        assert exc.value.name == unique_logger_name
        assert first.level == logging.DEBUG

    def test_placeholder_is_not_a_logger(self, log_config, unique_logger_name):
        """The PlaceHolder stdlib puts in for a dotted name's parent does not block it."""
        logging.getLogger(f"{unique_logger_name}.child")

        logger = LoggerFactory.create(unique_logger_name, log_config)

        assert logger.name == unique_logger_name


# =============================================================================
# Taking over a library's logger
# =============================================================================


def _library_logger(name: str, cls: type[logging.Logger]) -> logging.Logger:
    """Register a logger the way logging.getLogger() does when ``cls`` is the logger class.

    setLoggerClass is process-wide and other tests change it, so the class is explicit.
    """
    lg = cls(name)
    lg.parent = logging.root
    logging.root.manager.loggerDict[name] = lg
    return lg


@pytest.mark.unit
class TestTakeOver:
    """create() takes over a library's logger in place; the library keeps its reference."""

    @pytest.mark.parametrize(
        "cls", [logging.Logger, Logger], ids=["stdlib", "appinfra"]
    )
    def test_library_reference_logs_in_appinfra_format(
        self, log_config, unique_logger_name, capsys, cls
    ):
        """The library's own object is now the appinfra logger, with appinfra's handler."""
        lib = _library_logger(unique_logger_name, cls)
        plain = io.StringIO()
        lib.addHandler(logging.StreamHandler(plain))

        lg = LoggerFactory.create(unique_logger_name, log_config)
        lib.warning("library warning")

        out = capsys.readouterr().out
        assert lg is lib and isinstance(lib, Logger)
        assert "[W]" in out and "library warning" in out and unique_logger_name in out
        assert plain.getvalue() == ""  # the library's own handler was dropped

    def test_library_child_loggers_follow(self, log_config, unique_logger_name, capsys):
        """A library submodule's logger propagates to the taken-over one."""
        _library_logger(unique_logger_name, logging.Logger)
        child = logging.getLogger(f"{unique_logger_name}.sub")

        LoggerFactory.create(unique_logger_name, log_config)
        child.warning("submodule warning")

        out = capsys.readouterr().out
        assert "[W]" in out and "submodule warning" in out

    def test_taken_over_logger_is_owned(self, log_config, unique_logger_name):
        """After the takeover the name is an appinfra logger's: derive works, create raises."""
        _library_logger(unique_logger_name, logging.Logger)
        lg = LoggerFactory.create(unique_logger_name, log_config)

        assert LoggerFactory.derive(lg, "view")._root_logger is lg
        with pytest.raises(LoggerExistsError):
            LoggerFactory.create(unique_logger_name, log_config)

    def test_create_or_replace_takes_over_too(
        self, log_config, unique_logger_name, capsys
    ):
        """Nothing of appinfra's to replace: the library's object is taken over."""
        lib = _library_logger(unique_logger_name, logging.Logger)
        plain = io.StringIO()
        lib.addHandler(logging.StreamHandler(plain))

        lg = LoggerFactory.create_or_replace(unique_logger_name, log_config)
        lib.warning("library warning")

        assert lg is lib
        assert "library warning" in capsys.readouterr().out
        assert plain.getvalue() == ""

    @pytest.mark.parametrize(
        "cls", [logging.Logger, Logger], ids=["stdlib", "appinfra"]
    )
    def test_destroy_and_reconfigure_leave_it_alone(
        self, log_config, unique_logger_name, cls
    ):
        """A library's logger is not appinfra's to destroy or reconfigure."""
        lib = _library_logger(unique_logger_name, cls)
        handler = logging.StreamHandler(io.StringIO())
        lib.addHandler(handler)

        with pytest.raises(LoggerNotFoundError):
            LoggerFactory.destroy(unique_logger_name)
        with pytest.raises(LoggerNotFoundError):
            LoggerFactory.reconfigure(unique_logger_name, log_config)
        assert LoggerFactory.destroy_if_exists(unique_logger_name) is False

        assert logging.root.manager.loggerDict[unique_logger_name] is lib
        assert lib.handlers == [handler]

    def test_library_logger_subclass_is_not_taken_over(
        self, log_config, unique_logger_name
    ):
        """Rewriting a library's own Logger class would break its calls to it."""

        class LibraryLogger(logging.Logger):
            def audit(self, msg: str) -> None:
                self.info(msg)

        lib = _library_logger(unique_logger_name, LibraryLogger)

        with pytest.raises(LoggerExistsError):
            LoggerFactory.create(unique_logger_name, log_config)
        assert type(lib) is LibraryLogger


# =============================================================================
# reconfigure
# =============================================================================


@pytest.mark.unit
class TestReconfigure:
    """reconfigure() changes a live logger in place."""

    def test_applies_level_and_settings(self, log_config, unique_logger_name):
        """Everyone holding the logger sees the new level and holder settings."""
        logger = LoggerFactory.create(unique_logger_name, log_config)
        handlers = list(logger.handlers)

        updated = LoggerFactory.reconfigure(
            unique_logger_name,
            LogConfig(level=logging.WARNING, location=2, micros=True, colors=False),
        )

        assert updated is logger
        assert logger.level == logging.WARNING
        assert logger.get_level() == logging.WARNING
        assert logger._holder.location == 2 and logger._holder.micros is True
        assert logger.handlers == handlers  # handlers are left alone

    def test_lower_level_reaches_the_handler(self, unique_logger_name, capsys):
        """Reconfiguring info -> debug makes debug records print."""
        logger = LoggerFactory.create(unique_logger_name, LogConfig.from_params("info"))
        logger.debug("before")

        LoggerFactory.reconfigure(unique_logger_name, LogConfig.from_params("debug"))
        logger.debug("after")

        out = capsys.readouterr().out
        assert "before" not in out and "after" in out

    def test_keeps_a_handler_level_set_explicitly(self, unique_logger_name):
        """A handler built with its own level keeps it across reconfigure."""
        logger = (
            LoggingBuilder(unique_logger_name)
            .with_level("info")
            .with_console_handler(level="error")
            .build()
        )

        LoggerFactory.reconfigure(unique_logger_name, LogConfig.from_params("debug"))

        assert logger.level == logging.DEBUG
        assert [h.level for h in logger.handlers] == [logging.ERROR]

    def test_disabling(self, log_config, unique_logger_name):
        """level=False disables the logger, as at creation."""
        logger = LoggerFactory.create(unique_logger_name, log_config)

        LoggerFactory.reconfigure(unique_logger_name, LogConfig.from_params(False))

        assert logger.disabled is True

    def test_raises_when_absent(self, log_config, unique_logger_name):
        """There is nothing to reconfigure."""
        with pytest.raises(LoggerNotFoundError):
            LoggerFactory.reconfigure(unique_logger_name, log_config)

    def test_rejects_a_derived_view(self, log_config, unique_logger_name):
        """A view shares its root's settings; the root is left as it was."""
        root = LoggerFactory.create(unique_logger_name, log_config)
        view = LoggerFactory.derive(root, "view")

        with pytest.raises(LogConfigError, match="derived view"):
            LoggerFactory.reconfigure(
                view.name, LogConfig(level=logging.WARNING, location=2)
            )

        assert root._holder.location == 0
        assert view.level == logging.NOTSET


# =============================================================================
# destroy
# =============================================================================


@pytest.mark.unit
class TestDestroy:
    """destroy() frees a name, with every logger derived from it."""

    def test_frees_the_name(self, log_config, unique_logger_name):
        """After destroy, create() of the name works again."""
        old = LoggerFactory.create(unique_logger_name, log_config)

        LoggerFactory.destroy(unique_logger_name)
        new = LoggerFactory.create(unique_logger_name, log_config)

        assert new is not old
        assert (
            old.handlers == []
        )  # closed and removed; the old object still logs nowhere

    def test_removes_derived_loggers(self, log_config, unique_logger_name):
        """No view is left pointing at a removed logger."""
        parent = LoggerFactory.create(unique_logger_name, log_config)
        child = LoggerFactory.derive(parent, ["a", "b"])
        sibling = LoggerFactory.create(f"{unique_logger_name}-other", log_config)

        LoggerFactory.destroy(unique_logger_name)

        registry = logging.root.manager.loggerDict
        assert unique_logger_name not in registry and child.name not in registry
        assert registry[sibling.name] is sibling  # an unrelated name is untouched

    def test_root_destroy_spares_independent_loggers(
        self, log_config, unique_logger_name
    ):
        """A logger created with a '/' name is not a view of the root."""
        root = LoggerFactory.create_root(log_config)
        view = LoggerFactory.derive(root, "view")
        independent = LoggerFactory.create(f"/{unique_logger_name}", log_config)

        LoggerFactory.destroy("/")

        registry = logging.root.manager.loggerDict
        assert "/" not in registry and view.name not in registry
        assert registry[independent.name] is independent

    def test_close_error_raises_after_full_cleanup(
        self, log_config, unique_logger_name
    ):
        """A failing close() does not stop the rest; its error comes out at the end."""
        parent = LoggerFactory.create(unique_logger_name, log_config)
        view = LoggerFactory.derive(parent, "view")
        failing, later = _FailingCloseHandler(), _RecordingHandler()
        parent.addHandler(failing)
        parent.addHandler(later)

        with pytest.raises(OSError, match="disk full"):
            LoggerFactory.destroy(unique_logger_name)

        registry = logging.root.manager.loggerDict
        assert unique_logger_name not in registry and view.name not in registry
        assert parent.handlers == [] and later.closed

    def test_absent_raises(self, unique_logger_name):
        """Destroying a name nobody uses is an error: a typo or a second destroy."""
        with pytest.raises(LoggerNotFoundError):
            LoggerFactory.destroy(unique_logger_name)

    def test_destroy_if_exists(self, log_config, unique_logger_name):
        """Reports whether there was something to destroy, and never raises."""
        LoggerFactory.create(unique_logger_name, log_config)

        assert LoggerFactory.destroy_if_exists(unique_logger_name) is True
        assert LoggerFactory.destroy_if_exists(unique_logger_name) is False


class _RecordingHandler(logging.Handler):
    """A handler that remembers whether it was closed."""

    closed = False

    def emit(self, record: logging.LogRecord) -> None:
        pass

    def close(self) -> None:
        super().close()
        self.closed = True


class _FailingCloseHandler(_RecordingHandler):
    """A handler whose close() fails, as a file handler's final flush can."""

    def close(self) -> None:
        super().close()
        raise OSError("disk full")


@pytest.mark.unit
class TestCreateOrReplace:
    """create_or_replace() is destroy() then create()."""

    def test_replaces_an_existing_logger(self, log_config, unique_logger_name):
        """The old logger and its views go; a fresh logger takes the name."""
        old = LoggerFactory.create(unique_logger_name, log_config)
        view = LoggerFactory.derive(old, "view")

        new = LoggerFactory.create_or_replace(
            unique_logger_name, LogConfig.from_params("warning")
        )

        registry = logging.root.manager.loggerDict
        assert new is not old and registry[unique_logger_name] is new
        assert new.level == logging.WARNING
        assert old.handlers == [] and view.name not in registry

    def test_creates_when_absent(self, log_config, unique_logger_name):
        """With nothing to replace it is plain create()."""
        logger = LoggerFactory.create_or_replace(unique_logger_name, log_config)

        assert logging.root.manager.loggerDict[unique_logger_name] is logger


def _create_root_in_child(conn) -> None:
    """In a forked child: take over the inherited root name and log through both."""
    from appinfra.log.factory import LoggerFactory as Factory

    inherited = logging.root.manager.loggerDict["/"]
    try:
        own = Factory.create_root(LogConfig.from_params("info"))
        view = Factory.derive(own, "view")
        conn.send(
            (
                own is not inherited,
                view._root_logger is own,
                bool(inherited.handlers),
            )
        )
    except Exception as e:  # report instead of dying silently
        conn.send(repr(e))
    finally:
        conn.close()


@pytest.mark.unit
@pytest.mark.skipif(
    "fork" not in __import__("multiprocessing").get_all_start_methods(),
    reason="needs the fork start method",
)
def test_forked_child_may_create_an_inherited_name(log_config):
    """A logger inherited across fork belongs to the parent; the child can create the name."""
    import multiprocessing

    parent_root = LoggerFactory.create_root(log_config)
    LoggerFactory.derive(parent_root, "view")
    ctx = multiprocessing.get_context("fork")
    recv, send = ctx.Pipe(duplex=False)
    child = ctx.Process(target=_create_root_in_child, args=(send,))
    child.start()
    send.close()  # parent closes its end so recv can get EOF on child death
    try:
        assert recv.poll(10.0), "child did not report a result"
        result = recv.recv()
    finally:
        child.join(10.0)
        if child.is_alive():
            child.terminate()

    # new root, a view of the new root (not the inherited one), inherited lg still works
    assert result == (True, True, True)
    with pytest.raises(LoggerExistsError):  # in this process the name is still taken
        LoggerFactory.create_root(log_config)


# =============================================================================
# Test create_child method - Lines 107-122
# =============================================================================


@pytest.mark.unit
class TestCreateChild:
    """Test create_child method."""

    def test_create_child_from_parent(self, log_config, unique_logger_name):
        """Test create_child creates properly named child (lines 107-122)."""
        parent = LoggerFactory.create(unique_logger_name, log_config)

        child = LoggerFactory.create_child(parent, "child")

        assert child is not None
        assert child.name == f"{unique_logger_name}/child"

        # Cleanup
        parent.handlers.clear()
        child.handlers.clear()

    def test_create_child_from_root(self, log_config):
        """Test create_child from root logger."""
        root = LoggerFactory.create_root(log_config)

        child = LoggerFactory.create_child(root, "root_child")

        assert child.name == "/root_child"

        # Cleanup
        root.handlers.clear()
        child.handlers.clear()

    def test_create_child_inherits_config(self, log_config, unique_logger_name):
        """Test create_child inherits parent configuration."""
        parent = LoggerFactory.create(unique_logger_name, log_config)

        child = LoggerFactory.create_child(parent, "config_child")

        assert child.get_level() == parent.get_level()
        assert child.location == parent.location
        assert child.micros == parent.micros

        # Cleanup
        parent.handlers.clear()
        child.handlers.clear()


# =============================================================================
# Test derive method - Lines 136-155
# =============================================================================


@pytest.mark.unit
class TestDerive:
    """Test derive method."""

    def test_derive_with_single_tag(self, log_config, unique_logger_name):
        """Test derive with single tag string (lines 136-155)."""
        parent = LoggerFactory.create(unique_logger_name, log_config)

        derived = LoggerFactory.derive(parent, "tag1")

        assert derived.name == f"{unique_logger_name}/tag1"

        # Cleanup
        parent.handlers.clear()
        derived.handlers.clear()

    def test_derive_with_multiple_tags(self, log_config, unique_logger_name):
        """Test derive with list of tags."""
        parent = LoggerFactory.create(unique_logger_name, log_config)

        derived = LoggerFactory.derive(parent, ["tag1", "tag2", "tag3"])

        assert derived.name == f"{unique_logger_name}/tag1/tag2/tag3"

        # Cleanup
        parent.handlers.clear()
        derived.handlers.clear()

    def test_derive_from_root(self, log_config):
        """Test derive from root logger."""
        root = LoggerFactory.create_root(log_config)

        derived = LoggerFactory.derive(root, "derived_tag")

        # Root is "/" so derived name starts with /
        assert derived.name == "/derived_tag"

        # Cleanup
        root.handlers.clear()
        derived.handlers.clear()

    def test_derive_inherits_config(self, log_config, unique_logger_name):
        """Test derived logger inherits configuration."""
        parent = LoggerFactory.create(unique_logger_name, log_config)

        derived = LoggerFactory.derive(parent, ["service", "component"])

        assert derived.get_level() == parent.get_level()
        assert derived.location == parent.location

        # Cleanup
        parent.handlers.clear()
        derived.handlers.clear()


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
class TestFactoryIntegration:
    """Test factory integration scenarios."""

    def test_full_logger_hierarchy(self, log_config, unique_logger_name):
        """Test creating a full logger hierarchy."""
        # Create root
        root = LoggerFactory.create(unique_logger_name, log_config)

        # Create children
        child1 = LoggerFactory.create_child(root, "service_a")
        child2 = LoggerFactory.create_child(root, "service_b")

        # Derive from children
        derived1 = LoggerFactory.derive(child1, ["component", "subcomponent"])

        # Verify hierarchy
        assert child1.name == f"{unique_logger_name}/service_a"
        assert child2.name == f"{unique_logger_name}/service_b"
        assert derived1.name == f"{unique_logger_name}/service_a/component/subcomponent"

        # Cleanup
        for lg in [root, child1, child2, derived1]:
            lg.handlers.clear()

    def test_factory_with_extra_fields(self, log_config, unique_logger_name):
        """Test factory with extra fields."""
        extra = {"service": "api", "version": "1.0"}
        logger = LoggerFactory.create(
            f"{unique_logger_name}_extra", log_config, extra=extra
        )

        assert logger is not None
        # Extra fields are stored on the logger
        assert logger._extra == extra

        # Cleanup
        logger.handlers.clear()

    def test_factory_with_ordered_dict_extra(self, log_config, unique_logger_name):
        """Test factory with OrderedDict extra fields."""
        extra = collections.OrderedDict([("first", 1), ("second", 2)])
        logger = LoggerFactory.create(
            f"{unique_logger_name}_ordered", log_config, extra=extra
        )

        assert logger._extra == extra

        # Cleanup
        logger.handlers.clear()


# =============================================================================
# Test Hot-Reload of Location via Holder
# =============================================================================


@pytest.mark.unit
class TestLoggerHolderHotReload:
    """Test that logger location is hot-reloadable via registry.

    Note: location and micros are global settings read from the registry's
    default config. This enables hot-reload - all loggers read from the
    same source.
    """

    def test_logger_has_holder_set(self, unique_logger_name):
        """Test that created loggers have holder set."""
        config = LogConfig(level=logging.DEBUG, location=2, micros=False, colors=False)
        logger = LoggerFactory.create(unique_logger_name, config)

        assert logger._holder is not None
        assert isinstance(logger._holder, LogConfigHolder)

        # Cleanup
        logger.handlers.clear()

    def test_logger_location_reads_from_holder(self, unique_logger_name):
        """Test location property reads from holder."""
        config = LogConfig(level=logging.DEBUG, location=3, micros=False, colors=False)
        logger = LoggerFactory.create(unique_logger_name, config)

        # Logger reads location from holder
        assert logger.location == logger._holder.location
        assert logger.location == 3

        # Cleanup
        logger.handlers.clear()

    def test_logger_location_updates_on_holder_update(self, unique_logger_name):
        """Test location property updates when holder is updated."""
        config = LogConfig(level=logging.DEBUG, location=2, micros=False, colors=False)
        logger = LoggerFactory.create(unique_logger_name, config)

        # Initial location from holder
        assert logger.location == 2

        # Update the holder with new config
        new_config = LogConfig(
            level=logging.DEBUG, location=5, micros=False, colors=False
        )
        logger._holder.update(new_config)

        # Logger location should now reflect the new value
        assert logger.location == 5

        # Cleanup
        logger.handlers.clear()

    def test_child_logger_shares_holder_with_root(self, unique_logger_name):
        """Test child loggers share holder with root for consistent hot-reload."""
        config = LogConfig(level=logging.DEBUG, location=2, micros=False, colors=False)
        parent = LoggerFactory.create(unique_logger_name, config)
        child = LoggerFactory.create_child(parent, "child")

        # Both should have the same holder
        assert child._holder is parent._holder

        # Cleanup
        parent.handlers.clear()
        child.handlers.clear()

    def test_derived_logger_shares_holder_with_root(self, unique_logger_name):
        """Test derived loggers share holder with root for consistent hot-reload."""
        config = LogConfig(level=logging.DEBUG, location=2, micros=False, colors=False)
        parent = LoggerFactory.create(unique_logger_name, config)
        derived = LoggerFactory.derive(parent, ["service", "component"])

        # Both should have the same holder
        assert derived._holder is parent._holder

        # Cleanup
        parent.handlers.clear()
        derived.handlers.clear()

    def test_holder_update_affects_all_loggers_in_hierarchy(self, unique_logger_name):
        """Test holder update affects parent and all derived loggers."""
        config = LogConfig(level=logging.DEBUG, location=1, micros=False, colors=False)
        parent = LoggerFactory.create(unique_logger_name, config)
        child = LoggerFactory.create_child(parent, "child")
        derived = LoggerFactory.derive(parent, ["service", "component"])

        # All read location from shared holder
        assert parent.location == 1
        assert child.location == 1
        assert derived.location == 1

        # Update holder (shared by all)
        new_config = LogConfig(
            level=logging.DEBUG, location=4, micros=False, colors=False
        )
        parent._holder.update(new_config)

        # All should now show location=4 (they share the same holder)
        assert parent.location == 4
        assert child.location == 4
        assert derived.location == 4

        # Cleanup
        for lg in [parent, child, derived]:
            lg.handlers.clear()
