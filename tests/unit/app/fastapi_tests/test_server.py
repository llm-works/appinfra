# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for Server runtime."""

import gc
import sys
import threading
import weakref
from unittest.mock import MagicMock, call, patch

import pytest

from appinfra.app.fastapi.config.api import ApiConfig
from appinfra.app.fastapi.config.ipc import IPCConfig
from appinfra.runtime import Chan
from appinfra.service import State


class TestServer:
    """Tests for Server class."""

    @pytest.fixture
    def mock_lg(self):
        """Mock logger."""
        return MagicMock()

    @pytest.fixture
    def mock_dependencies(self):
        """Mock FastAPI dependencies."""
        with (
            patch("appinfra.app.fastapi.runtime.server.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.server.FastAPI") as mock_fastapi,
        ):
            mock_fastapi.return_value = MagicMock()
            yield mock_fastapi

    def test_initialization(self, mock_dependencies, mock_lg):
        """Test server initialization."""
        from appinfra.app.fastapi.runtime.server import Server

        config = ApiConfig()
        adapter = MagicMock()

        server = Server(mock_lg, name="test-server", config=config, adapter=adapter)

        assert server.name == "test-server"
        assert server.config is config
        assert server._adapter is adapter
        assert server.requests is None

    def test_is_subprocess_mode_false(self, mock_dependencies, mock_lg):
        """Test is_subprocess_mode without a requests Chan."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(mock_lg, name="test", config=ApiConfig(), adapter=MagicMock())

        assert server.is_subprocess_mode is False

    def test_is_subprocess_mode_true(self, mock_dependencies, mock_lg):
        """Test is_subprocess_mode with a requests Chan."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            requests=Chan(1, process=True),
        )

        assert server.is_subprocess_mode is True

    def test_is_running_no_subprocess(self, mock_dependencies, mock_lg):
        """Test is_running when no subprocess started."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(mock_lg, name="test", config=ApiConfig(), adapter=MagicMock())

        assert server.is_running is False

    def test_requests_property(self, mock_dependencies, mock_lg):
        from appinfra.app.fastapi.runtime.server import Server

        requests: Chan = Chan(1, process=True)
        server = Server(
            mock_lg,
            name="test",
            config=ApiConfig(),
            adapter=MagicMock(),
            requests=requests,
        )

        assert server.requests is requests

    def test_app_property_builds_on_demand(self, mock_dependencies, mock_lg):
        """Test app property builds app on first access."""
        from appinfra.app.fastapi.runtime.server import Server

        adapter = MagicMock()
        adapter.build.return_value = MagicMock()

        server = Server(mock_lg, name="test", config=ApiConfig(), adapter=adapter)

        app1 = server.app
        app2 = server.app

        # Should only build once
        adapter.build.assert_called_once()
        assert app1 is app2


@pytest.fixture
def runtime_deps():
    """FastAPI, the service Runtime and UvicornService, mocked where Server
    uses them: no process, queue or shared value is made."""
    with (
        patch("appinfra.app.fastapi.runtime.server.FASTAPI_AVAILABLE", True),
        patch("appinfra.app.fastapi.runtime.server.FastAPI"),
        patch("appinfra.app.fastapi.runtime.server.ServiceRuntime") as runtime_cls,
        patch("appinfra.app.fastapi.runtime.server.UvicornService") as service_cls,
    ):
        yield {
            "runtime_cls": runtime_cls,
            "runtime": runtime_cls.return_value,
            "service_cls": service_cls,
        }


def _subprocess_server(config: ApiConfig | None = None, **kwargs):
    from appinfra.app.fastapi.runtime.server import Server

    return Server(
        MagicMock(),
        name="test",
        config=config or ApiConfig(),
        adapter=MagicMock(),
        requests=Chan(1, process=True),
        **kwargs,
    )


def _runner(state: State, can_restart: bool = False) -> MagicMock:
    runner = MagicMock()
    runner.state = state
    runner.can_restart = can_restart
    return runner


class TestServerSubprocessMode:
    """start_subprocess() and stop() on the service Runtime."""

    def test_start_subprocess_requires_subprocess_mode(self, runtime_deps):
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            MagicMock(), name="test", config=ApiConfig(), adapter=MagicMock()
        )

        with pytest.raises(RuntimeError, match="subprocess mode"):
            server.start_subprocess()

    def test_start_subprocess_raises_if_running(self, runtime_deps):
        server = _subprocess_server()
        server._runner = _runner(State.RUNNING)

        with pytest.raises(RuntimeError, match="already running"):
            server.start_subprocess()

    def test_a_settled_server_starts_again(self, runtime_deps):
        """Failed with no restart left, the server can be started anew."""
        server = _subprocess_server()
        server._runner = _runner(State.FAILED, can_restart=False)

        server.start_subprocess()

        runtime_deps["runtime"].spawn.assert_called_once()

    def test_start_subprocess_runs_an_isolated_service_of_its_own_runtime(
        self, runtime_deps
    ):
        """Without a runtime given, it starts one, spawns the service isolated
        in it, and returns once ready()."""
        server = _subprocess_server()

        assert server.start_subprocess() is None

        runtime = runtime_deps["runtime"]
        runtime.start.assert_called_once()
        service = runtime_deps["service_cls"].return_value
        (spawned, _policy), kwargs = runtime.spawn.call_args
        assert spawned is service and kwargs == {"isolate": True}
        runtime.ready.assert_called_once_with(
            runtime.spawn.return_value, timeout=pytest.approx(30.0)
        )

    def test_the_runner_reports_its_transitions_to_the_service(self, runtime_deps):
        """The service hears of a run's end in the parent: its port clears."""
        server = _subprocess_server()
        server.start_subprocess()

        runner = runtime_deps["runtime"].spawn.return_value
        service = runtime_deps["service_cls"].return_value
        runner.on_state_change.assert_called_once_with(service.on_run_state)

    def test_the_service_shares_from_the_runtimes_context(self, runtime_deps):
        server = _subprocess_server()
        server.start_subprocess()

        kwargs = runtime_deps["service_cls"].call_args.kwargs
        assert kwargs["context"] is runtime_deps["runtime"].process_context

    def test_start_subprocess_spawns_into_a_given_runtime(self, runtime_deps):
        """A given runtime is used as is: neither made nor started here."""
        given = MagicMock()
        server = _subprocess_server(runtime=given)

        server.start_subprocess()

        runtime_deps["runtime_cls"].assert_not_called()
        given.start.assert_not_called()
        given.spawn.assert_called_once()

    @pytest.mark.parametrize(
        ("max_restarts", "max_retries"), [(0, sys.maxsize), (3, 3)]
    )
    def test_start_subprocess_maps_max_restarts(
        self, runtime_deps, max_restarts, max_retries
    ):
        """max_restarts=0 means unlimited restarts; other values pass through."""
        server = _subprocess_server(ApiConfig(max_restarts=max_restarts))
        server.start_subprocess()

        (_service, policy), _ = runtime_deps["runtime"].spawn.call_args
        assert policy.max_retries == max_retries

    @pytest.mark.parametrize("auto_restart", [True, False])
    def test_auto_restart_is_the_policys_restart_on_failure(
        self, runtime_deps, auto_restart
    ):
        server = _subprocess_server(ApiConfig(auto_restart=auto_restart))
        server.start_subprocess()

        (_service, policy), _ = runtime_deps["runtime"].spawn.call_args
        assert policy.restart_on_failure is auto_restart

    def test_start_subprocess_sets_default_ipc_config(self, runtime_deps):
        config = ApiConfig()
        assert config.ipc is None
        server = _subprocess_server(config)

        server.start_subprocess()

        assert isinstance(server._config.ipc, IPCConfig)

    @pytest.mark.parametrize("error", [TimeoutError("not up"), KeyboardInterrupt()])
    def test_a_start_that_does_not_come_up_leaves_nothing_running(
        self, runtime_deps, error
    ):
        """ready() fails or is interrupted: the service and the server's own
        runtime are stopped, and the error raised."""
        runtime = runtime_deps["runtime"]
        runtime.ready.side_effect = error
        server = _subprocess_server()

        with pytest.raises(type(error)):
            server.start_subprocess()

        runtime.stop_service.assert_called_once_with(
            runtime.spawn.return_value, timeout=5.0
        )
        runtime.stop.assert_called_once()
        assert server._runner is None

    @pytest.mark.parametrize("failing", ["service", "spawn"])
    def test_a_start_that_cannot_spawn_stops_its_own_runtime(
        self, runtime_deps, failing
    ):
        """The service cannot be made (a bad config) or spawned: the runtime
        started for it is stopped, and the error raised."""
        from appinfra.app.fastapi.errors import ConfigError

        runtime = runtime_deps["runtime"]
        error: Exception
        if failing == "service":
            error = ConfigError("Invalid port")
            runtime_deps["service_cls"].side_effect = error
        else:
            error = RuntimeError("cannot spawn")
            runtime.spawn.side_effect = error
        server = _subprocess_server()

        with pytest.raises(type(error)) as raised:
            server.start_subprocess()

        assert raised.value is error  # not another failure of the same type
        runtime.stop.assert_called_once()
        assert server._own_runtime is None

    def test_an_interrupted_spawn_stops_the_runner_it_left(self, runtime_deps):
        """Ctrl-C while spawn() waits for its reply: the runtime took the
        service all the same, and the server stops it in a given runtime."""
        given = MagicMock()
        spawned = MagicMock()

        def spawn(service, _policy, *, isolate):
            spawned.service = service
            given.services = {service.name: spawned}
            raise KeyboardInterrupt

        given.spawn.side_effect = spawn
        server = _subprocess_server(runtime=given)

        with pytest.raises(KeyboardInterrupt):
            server.start_subprocess()

        given.stop_service.assert_called_once_with(spawned, timeout=5.0)

    def test_a_refused_spawn_leaves_the_runtimes_service_alone(self, runtime_deps):
        """Another service of the same name is not the server's to stop."""
        given = MagicMock()

        def spawn(service, _policy, *, isolate):
            given.services = {service.name: MagicMock()}
            raise ValueError("a service of the same name is in the runtime")

        given.spawn.side_effect = spawn
        server = _subprocess_server(runtime=given)

        with pytest.raises(ValueError):
            server.start_subprocess()

        given.stop_service.assert_not_called()

    def test_a_stop_before_the_runner_is_known_stops_it(self, runtime_deps):
        """stop() from another thread while spawn() runs finds no runner yet:
        the start stops the runner once it has it, and fails."""
        from appinfra.service import RunError

        given = MagicMock()
        given.services = {}
        spawned = MagicMock()
        server = _subprocess_server(runtime=given)

        def spawn(_service, _policy, *, isolate):
            server.stop()
            return spawned

        given.spawn.side_effect = spawn

        with pytest.raises(RunError, match="stopped while starting"):
            server.start_subprocess()

        given.stop_service.assert_called_once_with(spawned, timeout=5.0)
        given.ready.assert_not_called()

    def test_stop_stops_the_service_and_its_own_runtime(self, runtime_deps):
        server = _subprocess_server()
        server.start_subprocess()
        runtime = runtime_deps["runtime"]

        server.stop(timeout=3.0)

        runtime.stop_service.assert_called_once_with(
            runtime.spawn.return_value, timeout=3.0
        )
        runtime.stop.assert_called_once_with(timeout=3.0)
        assert server._runner is None

    def test_stop_leaves_a_given_runtime_running(self, runtime_deps):
        given = MagicMock()
        server = _subprocess_server(runtime=given)
        server.start_subprocess()

        server.stop()

        given.stop_service.assert_called_once()
        given.stop.assert_not_called()

    def test_a_failed_service_stop_still_stops_its_own_runtime(self, runtime_deps):
        runtime = runtime_deps["runtime"]
        runtime.stop_service.side_effect = TimeoutError("outlived its kill")
        server = _subprocess_server()
        server.start_subprocess()

        with pytest.raises(TimeoutError):
            server.stop()

        runtime.stop.assert_called_once()
        assert server._runner is None  # it went with the runtime

    def test_a_failed_stop_in_a_given_runtime_is_retried(self, runtime_deps):
        """The child outlived its kill: the server keeps its runner, and a
        later stop() asks the runtime to stop it again."""
        given = MagicMock()
        given.stop_service.side_effect = [TimeoutError("outlived its kill"), None]
        server = _subprocess_server(runtime=given)
        server.start_subprocess()

        with pytest.raises(TimeoutError):
            server.stop()
        server.stop()

        spawned = given.spawn.return_value
        assert given.stop_service.call_args_list == [
            call(spawned, timeout=5.0),
            call(spawned, timeout=5.0),
        ]
        assert server._runner is None
        given.stop.assert_not_called()

    @pytest.mark.parametrize("given", [True, False])
    def test_a_negative_stop_timeout_changes_nothing(self, runtime_deps, given):
        runtime = MagicMock() if given else runtime_deps["runtime"]
        server = _subprocess_server(runtime=runtime if given else None)
        server.start_subprocess()

        with pytest.raises(ValueError, match="negative"):
            server.stop(timeout=-1.0)

        runtime.stop_service.assert_not_called()
        runtime.stop.assert_not_called()
        assert server._runner is runtime.spawn.return_value

    def test_stop_does_nothing_if_not_started(self, runtime_deps):
        server = _subprocess_server()

        server.stop()

        runtime_deps["runtime_cls"].assert_not_called()


class TestServerRun:
    """What the server reads of its current run."""

    @pytest.fixture
    def server(self, runtime_deps):
        return _subprocess_server()

    def test_process_is_the_current_runs(self, server):
        runner = _runner(State.RUNNING)
        server._runner = runner

        assert server.process is runner.task.process

    def test_no_task_no_process(self, server):
        """Between a crash and its restart, or in setup: no subprocess."""
        runner = _runner(State.FAILED, can_restart=True)
        runner.task = None
        server._runner = runner

        assert server.process is None
        assert server.pid is None
        assert server.is_running is False

    @pytest.mark.parametrize("alive", [True, False])
    def test_pid_and_is_running_read_the_current_detail(self, server, alive):
        runner = _runner(State.RUNNING)
        detail = runner.task.process.detail.return_value
        detail.pid, detail.alive = 4321, alive
        server._runner = runner

        assert server.pid == 4321
        assert server.is_running is alive


class TestServerValidation:
    """Tests for Server validation methods."""

    def test_validate_subprocess_mode_not_configured(self, runtime_deps):
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            MagicMock(), name="test", config=ApiConfig(), adapter=MagicMock()
        )

        with pytest.raises(RuntimeError, match="subprocess mode"):
            server._validate_subprocess_mode()

    @pytest.mark.parametrize(
        "runner",
        [_runner(State.STARTING), _runner(State.FAILED, can_restart=True)],
        ids=["starting", "restart-pending"],
    )
    def test_validate_subprocess_mode_already_running(self, runtime_deps, runner):
        server = _subprocess_server()
        server._runner = runner

        with pytest.raises(RuntimeError, match="already running"):
            server._validate_subprocess_mode()

    def test_validate_subprocess_mode_passes(self, runtime_deps):
        _subprocess_server()._validate_subprocess_mode()


class TestSettled:
    @pytest.mark.parametrize(
        ("state", "can_restart", "settled"),
        [
            (State.STOPPED, False, True),
            (State.DONE, False, True),
            (State.FAILED, False, True),
            (State.FAILED, True, False),
            (State.RUNNING, False, False),
            (State.STARTING, False, False),
        ],
    )
    def test_settled_is_for_good(self, state, can_restart, settled):
        """Stopped, done, or failed with no restart left; a failure with
        restarts left is not."""
        from appinfra.app.fastapi.runtime.server import _settled

        assert _settled(_runner(state, can_restart)) is settled

    def test_the_settle_wait_keeps_its_runner_in_no_cycle(self):
        """The hook _wait_settled() leaves on the runner holds it weakly: once
        dropped, the runner, its service and what that holds are freed at
        once, not whenever the cyclic GC next runs."""
        from appinfra.app.fastapi.runtime.server import _wait_settled
        from appinfra.service import Runner, Service

        class Idle(Service):
            name = "idle"

            def run(self) -> None:
                """Never run: the runner is made settled."""

        runner = Runner(Idle())
        runner._state = State.STOPPED  # Private: settled, so the wait returns
        freed = weakref.ref(runner)
        gc.disable()
        try:
            _wait_settled(runner)
            del runner
            assert freed() is None, "held by a cycle through its hook"
        finally:
            gc.enable()


class TestBuildUvicornLogConfig:
    """Tests for _build_uvicorn_log_config function."""

    @pytest.fixture
    def mock_dependencies(self):
        """Mock dependencies."""
        with (
            patch("appinfra.app.fastapi.runtime.server.FASTAPI_AVAILABLE", True),
            patch("appinfra.app.fastapi.runtime.server.FastAPI"),
        ):
            yield

    def test_default_config(self, mock_dependencies):
        """Test log config with defaults."""
        from appinfra.app.fastapi.runtime.server import _build_uvicorn_log_config

        config = ApiConfig()
        log_config = _build_uvicorn_log_config(config)

        assert log_config["version"] == 1
        assert log_config["disable_existing_loggers"] is True
        assert "uvicorn" in log_config["loggers"]
        assert log_config["loggers"]["uvicorn"]["level"] == "WARNING"

    def test_access_log_enabled(self, mock_dependencies):
        """Test log config with access logging enabled."""
        from appinfra.app.fastapi.config.uvicorn import UvicornConfig
        from appinfra.app.fastapi.runtime.server import _build_uvicorn_log_config

        config = ApiConfig(uvicorn=UvicornConfig(access_log=True, log_level="info"))
        log_config = _build_uvicorn_log_config(config)

        assert log_config["loggers"]["uvicorn.access"]["level"] == "INFO"


class TestServerStart:
    """Tests for server start methods."""

    def test_start_returns_once_settled_and_stops(self, runtime_deps):
        """Blocking start() in subprocess mode: a run already settled returns
        at once, and the server is stopped."""
        server = _subprocess_server()
        runtime_deps["runtime"].spawn.return_value = _runner(State.DONE)

        with patch.object(server, "stop", wraps=server.stop) as stop:
            server.start()

        stop.assert_called_once()

    def test_start_wakes_on_a_settling_transition(self, runtime_deps):
        """The state hook ends the wait: the runner settles while start()
        waits, and the hook it registered sets the event the wait is on."""
        runner = _runner(State.RUNNING)
        hooks: list = []
        runner.on_state_change.side_effect = hooks.append
        runtime_deps["runtime"].spawn.return_value = runner
        waited: list[bool] = []

        class SettlesOnWait(threading.Event):
            """The runner stops once the wait begins; its hooks hear of it."""

            def wait(self, timeout: float | None = None) -> bool:
                waited.append(True)
                runner.state = State.STOPPED
                for hook in hooks:
                    hook("uvicorn-test", State.RUNNING, State.STOPPED)
                assert self.is_set(), "the hook did not wake the wait"
                return True

        with patch("appinfra.app.fastapi.runtime.server.Event", SettlesOnWait):
            _subprocess_server().start()

        assert waited, "start() returned before it waited"

    def test_ctrl_c_while_blocking_stops_the_server(self, runtime_deps):
        server = _subprocess_server()
        runtime = runtime_deps["runtime"]

        with (
            patch(
                "appinfra.app.fastapi.runtime.server._wait_settled",
                side_effect=KeyboardInterrupt,
            ),
            pytest.raises(KeyboardInterrupt),
        ):
            server.start()

        runtime.stop_service.assert_called_once()
        runtime.stop.assert_called_once()

    def test_start_direct_mode(self, runtime_deps):
        """Test start() in direct mode."""
        from appinfra.app.fastapi.runtime.server import Server

        server = Server(
            MagicMock(), name="test", config=ApiConfig(), adapter=MagicMock()
        )

        with patch.object(server, "_run_direct") as mock_run:
            server.start()
            mock_run.assert_called_once()

    def test_run_direct(self, runtime_deps):
        """Test _run_direct runs uvicorn."""
        from appinfra.app.fastapi.runtime.server import Server

        mock_adapter = MagicMock()
        mock_app = MagicMock()
        mock_adapter.build.return_value = mock_app

        server = Server(
            MagicMock(),
            name="test",
            config=ApiConfig(host="127.0.0.1", port=9000),
            adapter=mock_adapter,
        )

        # uvicorn is lazily imported, so mock it in sys.modules
        mock_uvicorn = MagicMock()
        with patch.dict(sys.modules, {"uvicorn": mock_uvicorn}):
            server._run_direct()

            mock_uvicorn.run.assert_called_once()
            call_args = mock_uvicorn.run.call_args
            assert call_args[0][0] is mock_app
            assert call_args[1]["host"] == "127.0.0.1"
            assert call_args[1]["port"] == 9000


class TestUvicornServiceConfig:
    """UvicornService checks its configuration when made, in the parent: its
    setup() runs in the child."""

    def test_rejects_multiple_workers(self):
        """workers != 1 is refused: the subprocess passes uvicorn an app object."""
        from appinfra.app.fastapi.config.uvicorn import UvicornConfig
        from appinfra.app.fastapi.errors import ConfigError
        from appinfra.app.fastapi.runtime.service import UvicornService

        config = ApiConfig(uvicorn=UvicornConfig(workers=4))
        with pytest.raises(ConfigError, match="workers"):
            UvicornService(MagicMock(), "api", MagicMock(), config, MagicMock())

    @pytest.mark.parametrize("port", [8000, 0])
    def test_name_is_the_server_name_whatever_the_port(self, port: int):
        """Two servers on OS-picked ports are told apart in process and log names."""
        from appinfra.app.fastapi.runtime.service import UvicornService

        service = UvicornService(
            MagicMock(), "myapi", MagicMock(), ApiConfig(port=port), MagicMock()
        )
        assert service.name == "uvicorn-myapi"

    @pytest.mark.parametrize("port", [-1, 65536])
    def test_rejects_a_port_out_of_range(self, port: int):
        from appinfra.app.fastapi.errors import ConfigError
        from appinfra.app.fastapi.runtime.service import UvicornService

        with pytest.raises(ConfigError, match="port"):
            UvicornService(
                MagicMock(), "api", MagicMock(), ApiConfig(port=port), MagicMock()
            )

    def test_rejects_no_host(self):
        from appinfra.app.fastapi.errors import ConfigError
        from appinfra.app.fastapi.runtime.service import UvicornService

        with pytest.raises(ConfigError, match="Host"):
            UvicornService(
                MagicMock(), "api", MagicMock(), ApiConfig(host=""), MagicMock()
            )
