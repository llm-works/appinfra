# FastAPI Server Integration

HTTP server framework using FastAPI with subprocess isolation and service orchestration.

## Examples

### fastapi_server.py
Demonstrates three modes of the FastAPI server framework.

**What you'll learn:**
- Direct mode server (blocking, simple deployments)
- Subprocess mode with IPC (non-blocking, auto-restart)
- AppBuilder integration with ServerPlugin
- Queue-based communication patterns

**Run:**
```bash
# Direct mode (default) - blocking server
~/.venv/bin/python examples/07_fastapi/fastapi_server.py

# Subprocess mode with IPC demo
~/.venv/bin/python examples/07_fastapi/fastapi_server.py --subprocess

# AppBuilder integration
~/.venv/bin/python examples/07_fastapi/fastapi_server.py --cli serve
```

**Key concepts:**
- `ServerBuilder` - Fluent API for server configuration
- `ServerPlugin` - CLI integration for AppBuilder
- `Server.start()` - Direct mode (blocking)
- `Server.start_subprocess()` - Subprocess mode (non-blocking)

---

## Server Modes

### Direct Mode
Runs uvicorn in the current process. Simple and suitable for development.

```python
from appinfra.app.fastapi import ServerBuilder
from appinfra.log import Logger

lg = Logger("my-api")
server = (
    ServerBuilder(lg, "my-api")
    .with_port(8000)
    .routes.with_route("/health", health_handler)
    .done()
    .build()
)

server.start()  # Blocking
```

### Subprocess Mode
Runs uvicorn in a separate process with queue-based IPC.

```python
import multiprocessing as mp

request_q: mp.Queue = mp.Queue()
response_q: mp.Queue = mp.Queue()

server = (
    ServerBuilder(lg, "worker-api")
    .with_port(8001)
    .subprocess.with_ipc(request_q, response_q)
    .with_auto_restart(enabled=True, max_restarts=3)
    .done()
    .routes.with_route("/health", health_handler)
    .done()
    .build()
)

proc = server.start_subprocess()  # Non-blocking
```

### CLI Integration
Add HTTP server capability to CLI applications.

```python
from appinfra.app.builder import AppBuilder
from appinfra.app.fastapi import ServerBuilder, ServerPlugin

server = (
    ServerBuilder(lg, "cli-api")
    .with_port(8002)
    .routes.with_route("/health", health_handler)
    .done()
    .build()
)

app = (
    AppBuilder("myapp")
    .tools.with_plugin(ServerPlugin(server))
    .done()
    .build()
)

# Now: myapp serve
```

## Features

- **Fluent Builder API** - Chainable configuration
- **Subprocess Isolation** - Server crashes don't affect main process
- **Auto-Restart** - Configurable automatic recovery
- **IPC Queues** - Type-safe request/response communication
- **CLI Integration** - ServerPlugin for AppBuilder

## Best Practices

1. **Use subprocess mode for production** - Isolation and auto-restart
2. **Handle graceful shutdown** - Call `server.stop()` on SIGTERM/SIGINT
3. **Configure auto-restart limits** - Prevent infinite restart loops
4. **Use typed dataclasses for IPC** - Clear request/response contracts

## Troubleshooting

### Port already in use
```bash
lsof -i :8000
kill -9 <PID>
```

### Subprocess not starting
- Check if uvicorn is installed: `pip install uvicorn`
- Verify multiprocessing spawn method is compatible

### IPC messages not received
- Ensure queues are created before server start
- Check queue timeouts in your message handlers

## Related Documentation

- [FastAPI API Reference](../../docs/api/fastapi.md) - Complete API documentation
- [Service Framework](../../docs/api/service.md) - Service orchestration
- [Subprocess Management](../../docs/api/subprocess.md) - Process lifecycle
- [Main README](../README.md) - Full examples index
