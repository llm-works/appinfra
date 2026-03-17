# FastAPI Server Framework

Production-ready FastAPI + Uvicorn server framework with subprocess isolation and queue-based IPC.

## Installation

```bash
pip install appinfra[fastapi]
```

## Quick Start

### Simple Server (Direct Mode)

```python
from appinfra.app.fastapi import ServerBuilder
from appinfra.log import Logger

async def health():
    return {"status": "ok"}

lg = Logger("myapi")
server = (ServerBuilder(lg, "myapi")
    .with_port(8000)
    .routes.with_route("/health", health).done()
    .build())

server.start()  # Blocking
```

### Subprocess Mode with IPC

For CPU-intensive work, run the API server in a subprocess while the main process handles
computation:

```python
import multiprocessing as mp
from appinfra.app.fastapi import ServerBuilder
from appinfra.log import Logger

request_q, response_q = mp.Queue(), mp.Queue()

lg = Logger("worker-api")
server = (ServerBuilder(lg, "worker-api")
    .with_port(8000)
    .routes.with_route("/health", health).done()
    .subprocess
        .with_ipc(request_q, response_q)
        .with_auto_restart(enabled=True)
        .done()
    .build())

proc = server.start_subprocess()  # Non-blocking

# Main process handles requests
while True:
    request = request_q.get()
    result = process(request)
    response_q.put(result)
```

**Note:** The Logger is required for queue-based subprocess logging. The subprocess inherits the
main process log level, so exception handlers using `self._lg` log at the correct level.

### AppBuilder Integration

```python
from appinfra.app import AppBuilder
from appinfra.app.fastapi import ServerBuilder, ServerPlugin
from appinfra.log import Logger

lg = Logger("myapi")
server = ServerBuilder(lg, "myapi").with_port(8000).build()

app = (AppBuilder("myapp")
    .tools.with_plugin(ServerPlugin(server)).done()
    .build())

# CLI: myapp serve
```

## ServerBuilder

Fluent builder for configuring FastAPI servers.

```python
from appinfra.app.fastapi import ServerBuilder
from appinfra.log import Logger

lg = Logger("myapi")
server = (ServerBuilder(lg, "myapi")
    # Server binding
    .with_host("0.0.0.0")
    .with_port(8000)

    # OpenAPI metadata
    .with_title("My API")
    .with_description("API description")
    .with_version("1.0.0")

    # Timeouts
    .with_timeout(30.0)

    # Bulk configuration
    .with_config(ApiConfig(...))

    .build())
```

### Route Configuration

Access via `.routes`:

```python
server = (ServerBuilder(lg, "myapi")
    .routes
        # Simple route
        .with_route("/health", health_handler)

        # Route with methods
        .with_route("/data", data_handler, methods=["POST", "PUT"])

        # Include a router
        .with_router(api_router, prefix="/api/v1", tags=["v1"])

        # CORS
        .with_cors(
            origins=["http://localhost:3000"],
            allow_credentials=True,
            allow_methods=["GET", "POST"]
        )

        # Middleware
        .with_middleware(CustomMiddleware, timeout=30)

        # Exception handlers
        .with_exception_handler(ValueError, error_handler)

        .done()
    .build())
```

### Subprocess Configuration

Access via `.subprocess`:

```python
server = (ServerBuilder(lg, "myapi")
    .subprocess
        # IPC queues (required for subprocess mode)
        .with_ipc(request_q, response_q)

        # Auto-restart on crash
        .with_auto_restart(enabled=True, delay=2.0, max_restarts=10)

        # Log isolation
        .with_log_file("/var/log/api.log")

        # IPC tuning
        .with_poll_interval(0.01)      # Response polling (10ms)
        .with_response_timeout(30.0)   # Per-request timeout
        .with_max_pending(200)         # Max concurrent requests
        .with_health_reporting(True)   # Include IPC in health endpoint

        # Or bulk config
        .with_config(IPCConfig(...))

        .done()
    .build())
```

### Lifecycle Callbacks

Register callbacks for application lifecycle events:

```python
from contextlib import asynccontextmanager

# Startup/shutdown callbacks
async def init_db(app):
    app.state.db = await create_db_pool()

async def close_db(app):
    await app.state.db.close()

server = (ServerBuilder(lg, "myapi")
    .with_on_startup(init_db, name="init_db")
    .with_on_shutdown(close_db, name="close_db")
    .build())
```

Or use FastAPI's modern lifespan pattern:

```python
@asynccontextmanager
async def lifespan(app):
    # Startup
    app.state.db = await create_db_pool()
    yield
    # Shutdown
    await app.state.db.close()

server = (ServerBuilder(lg, "myapi")
    .with_lifespan(lifespan)
    .build())
```

**Note:** Using both `with_lifespan()` and startup/shutdown callbacks raises `ConfigError` at build
time. Choose one approach: either use a lifespan context manager or individual callbacks.

#### Request/Response Callbacks

Run callbacks on every request:

```python
async def log_request(request):
    logger.info(f"{request.method} {request.url}")

async def add_headers(request, response):
    response.headers["X-Request-ID"] = str(uuid4())
    return response  # Must return response

async def log_error(request, exc):
    logger.error(f"Error handling {request.url}: {exc}")

server = (ServerBuilder(lg, "myapi")
    .with_on_request(log_request)
    .with_on_response(add_headers)
    .with_on_exception(log_error)
    .build())
```

**Note:** Due to BaseHTTPMiddleware limitations, reading the request body in `with_on_request`
callbacks (via `request.body()` or `request.json()`) will prevent the route handler from reading it
again. For body access, use custom middleware via `routes.with_middleware()` instead.

#### Execution Order

Request/response callbacks run **inside** custom middleware (added via `routes.with_middleware()`).
This means callbacks have access to state set by your middleware:

```
Request flow:  custom middleware → CORS → request callbacks → route handler
Response flow: route handler → response callbacks → CORS → custom middleware
```

Due to Starlette's LIFO (Last In, First Out) middleware ordering, custom middleware (added last)
runs first on requests. This allows request callbacks to access authentication state, user context,
or other values injected by your middleware.

#### Error Handling

- **Startup failures:** Raises `CallbackError` with callback name for debugging
- **Shutdown failures:** Logs error (if logger available), then raises `CallbackError`
- **Configuration conflicts:** Using both `with_lifespan()` and startup/shutdown callbacks raises
  `ConfigError` at build time

### Logger Access in Subprocess Mode

In subprocess mode, the logger is stored on **`app.state.lg`** at startup and accessed differently
depending on context:

- **`app.state.lg`** - App-scoped logger, set at startup. Middleware accesses this via
  `request.app.state.lg` since they receive a request object.
- **`request.state.lg`** - Per-request copy, set by middleware. Use in **route handlers**.

#### Route Handlers

```python
from fastapi import Request
from starlette.responses import JSONResponse

@router.post("/process")
async def process(request: Request):
    try:
        result = await do_work()
        return {"result": result}
    except TimeoutError as e:
        request.state.lg.error("request timeout", extra={"error": str(e)})
        return JSONResponse({"error": "timeout"}, status_code=504)
```

#### Custom Middleware

Middleware runs before the logger injection middleware, so `request.state.lg` is not yet set.
Use `request.app.state.lg` instead:

```python
from starlette.middleware.base import BaseHTTPMiddleware

class TraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        lg = request.app.state.lg  # Use app.state, not request.state
        if lg and request.url.path.startswith("/v1/"):
            lg.trace("request", extra={"path": request.url.path})
        return await call_next(request)

# Register via builder
server = (ServerBuilder(lg, "api")
    .routes.with_middleware(TraceMiddleware).done()
    .build())
```

**Why the difference?** Due to Starlette's middleware ordering (LIFO), custom middleware added via
`with_middleware()` runs before the logger injection middleware. The logger is stored on
`app.state.lg` at startup, making it immediately available to all middleware.

### Exception Handlers in Subprocess Mode

Exception handlers containing `Logger` instances cannot be used directly in subprocess mode because
`Logger` cannot be pickled. Build-time validation will raise `ConfigError` if an unpicklable
handler is detected. Use the `ExceptionHandler` base class to handle Logger serialization
automatically:

```python
from appinfra.app.fastapi import ServerBuilder, ExceptionHandler
from appinfra.log import Logger
from starlette.responses import JSONResponse

class TimeoutHandler(ExceptionHandler):
    async def handle(self, request, exc: TimeoutError):
        # self._lg is automatically injected after unpickling
        self._lg.warning("request timeout", extra={"path": str(request.url.path)})
        return JSONResponse({"error": "timeout"}, status_code=504)

lg = Logger("api")
server = (ServerBuilder(lg, "api")
    .routes
        .with_exception_handler(TimeoutError, TimeoutHandler(lg))
        .done()
    .subprocess.with_ipc(request_q, response_q).done()
    .build())
```

**How it works:**
1. `ExceptionHandler.__getstate__()` strips Logger during pickle (subprocess spawn)
2. Framework calls `set_logger()` with subprocess Logger after unpickling
3. Handler's `handle()` method can use `self._lg` normally

**Build-time validation:** If a handler cannot be pickled and doesn't implement `LoggerInjectable`,
`build()` raises `RuntimeError` with guidance on how to fix it.

For custom implementations, implement the `LoggerInjectable` protocol (`set_logger()` method) and
handle `__getstate__`/`__setstate__` yourself.

### Uvicorn Configuration

Access via `.uvicorn`:

```python
server = (ServerBuilder(lg, "myapi")
    .uvicorn
        .with_workers(4)
        .with_log_level("info")
        .with_access_log(True)
        .with_ssl("/path/to/key.pem", "/path/to/cert.pem")
        .with_timeout_keep_alive(30)
        .with_limit_concurrency(100)
        .with_limit_max_requests(1000)
        .with_backlog(4096)

        # Or bulk config
        .with_config(UvicornConfig(...))

        .done()
    .build())
```

## Server

Runtime server instance returned by `ServerBuilder.build()`.

```python
server = ServerBuilder(lg, "myapi").build()

# Properties
server.name              # Server name
server.config            # ApiConfig
server.app               # FastAPI instance (built on first access)
server.is_subprocess_mode  # True if IPC queues configured
server.is_running        # True if subprocess is alive
server.request_queue     # Request queue (subprocess mode)
server.response_queue    # Response queue (subprocess mode)

# Methods
server.start()           # Run server (blocking)
server.start_subprocess()  # Start in subprocess (non-blocking, returns Process)
server.stop()            # Stop subprocess
```

## IPCChannel

Async IPC for FastAPI route handlers to communicate with the main process. Wraps
`AsyncProcessChannel` from the service package.

```python
from fastapi import Request

async def process_handler(request: Request):
    ipc: IPCChannel = request.app.state.ipc_channel

    # Submit request and wait for response
    # Request object must have an `id` attribute for routing
    response = await ipc.submit(
        request=WorkRequest(id="unique-id", data="..."),
        timeout=30.0  # Optional, defaults to config
    )

    return response
```

### Streaming Responses

```python
from fastapi.responses import StreamingResponse

async def stream_handler(request: Request):
    ipc: IPCChannel = request.app.state.ipc_channel

    async def generate():
        async for chunk in ipc.submit_stream(WorkRequest(id="req-id", prompt="...")):
            yield chunk.data
            if chunk.is_final:
                break

    return StreamingResponse(generate())
```

## IPC Pattern Guide

Complete guide to implementing the subprocess IPC pattern.

### Message Protocol

Request and response messages **must have an `id` attribute** for routing:

```python
from dataclasses import dataclass

@dataclass
class WorkRequest:
    id: str          # Required: unique identifier for routing
    prompt: str      # Your data fields
    max_tokens: int

@dataclass
class WorkResponse:
    id: str          # Required: must match request.id
    result: str      # Your data fields
    error: str | None = None

# For streaming responses
@dataclass
class StreamChunk:
    id: str          # Required: must match request.id
    data: str
    is_final: bool   # Required: True on last chunk
```

The `id` field is how IPCChannel routes responses back to the correct waiting handler. Without it,
responses are logged as warnings and discarded.

### Handler Pattern

Handlers access IPCChannel via `request.app.state.ipc_channel`:

```python
from uuid import uuid4
from fastapi import APIRouter, Request, HTTPException

router = APIRouter()

@router.post("/generate")
async def generate(body: GenerateRequest, request: Request):
    ipc = request.app.state.ipc_channel

    # Create request with unique ID (id attribute required for routing)
    work_request = WorkRequest(id=str(uuid4()), prompt=body.prompt, max_tokens=body.max_tokens)

    # Submit and wait for response
    response = await ipc.submit(work_request, timeout=60.0)

    if response.error:
        raise HTTPException(status_code=500, detail=response.error)
    return {"result": response.result}
```

For streaming responses:

```python
from fastapi.responses import StreamingResponse

@router.post("/stream")
async def stream(body: GenerateRequest, request: Request):
    ipc = request.app.state.ipc_channel
    work_request = WorkRequest(id=str(uuid4()), prompt=body.prompt, max_tokens=body.max_tokens)

    async def generate():
        async for chunk in ipc.submit_stream(work_request):
            yield chunk.data
            if chunk.is_final:
                break

    return StreamingResponse(generate(), media_type="text/plain")
```

### Main Process Loop

The main process reads requests, processes them, and sends responses:

```python
import multiprocessing as mp
from queue import Empty

def run_worker(request_q: mp.Queue, response_q: mp.Queue):
    """Main process worker loop."""
    while True:
        try:
            request = request_q.get(timeout=0.1)
        except Empty:
            continue

        # Process the request (your logic here)
        try:
            result = do_inference(request.prompt, request.max_tokens)
            response = WorkResponse(id=request.id, result=result)
        except Exception as e:
            response = WorkResponse(id=request.id, result="", error=str(e))

        # Response id MUST match request.id for routing
        response_q.put(response)
```

### Complete Example

```python
import multiprocessing as mp
from appinfra.app.fastapi import ServerBuilder
from appinfra.log import Logger

# Create IPC queues
request_q: mp.Queue = mp.Queue()
response_q: mp.Queue = mp.Queue()

# Build server with IPC
lg = Logger("worker-api")
server = (ServerBuilder(lg, "worker-api")
    .with_port(8000)
    .subprocess
        .with_ipc(request_q, response_q)
        .with_response_timeout(60.0)
        .with_auto_restart(enabled=True)
        .done()
    .routes
        .with_router(router)  # Router with /generate, /stream endpoints
        .done()
    .build())

# Start server subprocess (non-blocking)
proc = server.start_subprocess()

# Main process handles compute-intensive work
try:
    run_worker(request_q, response_q)
finally:
    server.stop()
```

See `examples/07_fastapi/fastapi_server.py` for a complete working implementation.

## Configuration Classes

### ApiConfig

Main server configuration:

```python
from appinfra.app.fastapi import ApiConfig, UvicornConfig, IPCConfig

config = ApiConfig(
    # Server binding
    host="0.0.0.0",           # Bind address
    port=8000,                # Bind port

    # OpenAPI metadata
    title="My API",           # API title
    description="...",        # API description
    version="1.0.0",          # API version

    # Subprocess settings
    response_timeout=60.0,    # Default timeout (when no IPC)
    log_file="/var/log/api.log",  # Subprocess log file
    auto_restart=True,        # Restart on crash
    restart_delay=1.0,        # Delay before restart
    max_restarts=5,           # Max restarts (0=unlimited)

    # Nested configs
    uvicorn=UvicornConfig(...),
    ipc=IPCConfig(...),       # None = direct mode
)
```

### UvicornConfig

Uvicorn server settings:

```python
from appinfra.app.fastapi import UvicornConfig

config = UvicornConfig(
    workers=4,                # Worker processes
    timeout_keep_alive=5,     # Keep-alive timeout
    limit_concurrency=None,   # Max concurrent connections
    limit_max_requests=None,  # Max requests per worker
    backlog=2048,             # Socket backlog
    log_level="warning",      # Log level
    access_log=False,         # Access logging
    ssl_keyfile=None,         # SSL key path
    ssl_certfile=None,        # SSL cert path
)
```

### IPCConfig

IPC behavior settings:

```python
from appinfra.app.fastapi import IPCConfig

config = IPCConfig(
    poll_interval=0.01,       # Response polling (10ms = 100 polls/sec)
    response_timeout=60.0,    # Default request timeout
    max_pending=100,          # Max pending requests
    enable_health_reporting=True,  # IPC status in health endpoint
)
```

## ServerPlugin

Integrates server with AppBuilder for CLI apps:

```python
from appinfra.app import AppBuilder
from appinfra.app.fastapi import ServerBuilder, ServerPlugin
from appinfra.log import Logger

lg = Logger("myapi")
server = ServerBuilder(lg, "myapi").with_port(8000).build()

app = (AppBuilder("myapp")
    .tools.with_plugin(ServerPlugin(server)).done()
    .build())
```

This adds a `serve` command to your CLI:

```bash
myapp serve              # Start server
myapp serve --port 9000  # Override port
```

## Architecture

```
┌─────────────────┐     mp.Queue      ┌──────────────────┐
│   Main Process  │ ◄───────────────► │   FastAPI        │
│                 │    request_q       │   Subprocess     │
│  - Heavy compute│    response_q     │                  │
│  - ML inference │                   │  - HTTP handling │
│  - Data loading │                   │  - Routing       │
└─────────────────┘                   │  - Validation    │
                                      └──────────────────┘
```

**Why subprocess isolation?**

- Python GIL: CPU-bound work in main process doesn't block HTTP handling
- Memory isolation: API server crashes don't affect main process
- Auto-restart: Server recovers from crashes automatically
- Log isolation: Separate log files for debugging

## See Also

- [Application Framework](app.md) - Core application classes
- [AppBuilder](app-builder.md) - Fluent builder API
