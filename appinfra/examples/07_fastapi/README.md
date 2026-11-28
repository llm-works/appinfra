# FastAPI Server Integration

HTTP server framework using FastAPI with subprocess isolation and service orchestration.

## Examples

### fastapi_server.py
Demonstrates two modes of the FastAPI server framework.

**What you'll learn:**
- Direct mode server (blocking, simple deployments)
- Subprocess mode with IPC (non-blocking, auto-restart)
- Queue-based communication patterns

**Run:**
```bash
# Direct mode (default) - blocking server
~/.venv/bin/python examples/07_fastapi/fastapi_server.py

# Subprocess mode with IPC demo
~/.venv/bin/python examples/07_fastapi/fastapi_server.py --subprocess
```

**Key concepts:**
- `ServerBuilder` - Fluent API for server configuration
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
    .with_port(25442)
    .routes.with_route("/health", health_handler)
    .done()
    .build()
)

server.start()  # Blocking
```

### Subprocess Mode
Runs uvicorn in a separate process with Chan-based IPC: its routes send requests to the main
process on `server.requests`, each with a Chan to reply on.

```python
server = (
    ServerBuilder(lg, "worker-api")
    .with_port(25443)
    .subprocess.with_ipc()  # makes server.requests
    .with_auto_restart(True)
    .with_max_restarts(3)
    .done()
    .routes.with_route("/health", health_handler)
    .with_route("/work/{data}", work_handler)  # await ipc.submit(WorkRequest(data))
    .done()
    .build()
)

server.start_subprocess()  # Non-blocking: returns once serving
request, reply = server.requests.recv(timeout=1.0)
reply.send(WorkResponse(result=request.data.upper()))
```

## Features

- **Fluent Builder API** - Chainable configuration
- **Subprocess Isolation** - Server crashes don't affect main process
- **Auto-Restart** - Configurable automatic recovery
- **IPC Queues** - Type-safe request/response communication

## Best Practices

1. **Use subprocess mode for production** - Isolation and auto-restart
2. **Handle graceful shutdown** - Call `server.stop()` on SIGTERM/SIGINT
3. **Configure auto-restart limits** - Prevent infinite restart loops
4. **Use typed dataclasses for IPC** - Clear request/response contracts

## Troubleshooting

### Port already in use
```bash
lsof -i :25442   # direct mode; :25443 for subprocess mode
kill -9 <PID>
```

### Subprocess not starting
- Check if uvicorn is installed: `pip install uvicorn`
- Verify multiprocessing spawn method is compatible

### IPC requests not answered
- Check the server was built with `.subprocess.with_ipc()`: without it, `server.requests` is `None`
- Check the main process reads `server.requests` and answers each request on its reply Chan
- Check it replies before the route's timeout (`submit(..., timeout=...)`, default
  `IPCConfig.response_timeout`); a reply after that raises `ChanClosedError`

## Related Documentation

- [FastAPI API Reference](../../docs/api/fastapi.md) - Complete API documentation
- [Service Framework](../../docs/api/service.md) - Service orchestration
- [Subprocess Management](../../docs/api/subprocess.md) - Process lifecycle
- [Main README](../README.md) - Full examples index
