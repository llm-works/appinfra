# Network

TCP and HTTP server components for building network services with background processing.

## Overview

The network module provides server infrastructure for applications that need to serve HTTP requests
while performing background tasks. Supports single-process and multiprocessing modes with ticker
integration.

**Use cases:**
- Web APIs with periodic data updates
- Monitoring services with health checks
- Data processing servers with background workers

## TCPServer

Main server class with flexible execution modes.

```python
class TCPServer:
    def __init__(
        self,
        lg: Logger,
        port: int,
        handler: HTTPRequestHandler,
        ticker: Ticker | None = None,
    ): ...

    def run(self) -> int: ...
```

**Parameters:**

| Parameter | Description |
|-----------|-------------|
| `lg` | Logger instance for server operations |
| `port` | Port number to listen on |
| `handler` | Request handler instance |
| `ticker` | Optional ticker for background processing |

**Execution Modes:**

- **Single-process mode** (no ticker): Runs everything in current process, uses threading
- **Multiprocessing mode** (with ticker): Runs ticker in separate process for better isolation

## HTTPRequestHandler

Base class for handling HTTP requests.

```python
class HTTPRequestHandler:
    def do_GET(self, instance) -> None: ...
    def do_HEAD(self, instance) -> None: ...
    def do_POST(self, instance) -> None: ...
```

The `instance` parameter is the actual request handler with access to:
- `instance.send_response(code)` - Send HTTP status
- `instance.send_header(name, value)` - Send header
- `instance.end_headers()` - End header section
- `instance.wfile` - Output stream for response body
- `instance.rfile` - Input stream for request body
- `instance.headers` - Request headers

## Basic HTTP Server

```python
from appinfra.net import TCPServer, HTTPRequestHandler
from appinfra.log import LoggingBuilder


class MyHandler(HTTPRequestHandler):
    def do_GET(self, instance):
        instance.send_response(200)
        instance.send_header("Content-type", "text/html")
        instance.end_headers()
        instance.wfile.write(b"Hello, World!")


logger = LoggingBuilder("server").with_level("info").console_handler().build()
server = TCPServer(logger, 8080, MyHandler())
server.run()
```

## Server with Background Ticker

Combine HTTP serving with periodic background tasks:

```python
from appinfra.net import TCPServer, HTTPRequestHandler
from appinfra.time import Ticker, TickerHandler
import json


class MyTickerHandler(Ticker, TickerHandler, HTTPRequestHandler):
    def __init__(self, lg):
        self._lg = lg
        Ticker.__init__(self, self, secs=5)  # Tick every 5 seconds

    def ticker_start(self, *args, **kwargs):
        """Initialize shared state for multiprocessing."""
        # Extract manager from positional args (passed by TCPServer in multiprocessing mode)
        manager = args[0] if args else kwargs.get("manager")
        if manager is not None:
            # Multiprocessing mode - use manager for shared state
            self._lock = manager.Lock()
            self._state = manager.dict()
            self._state["ticks"] = 0
        else:
            # Single-process mode - use threading
            import threading

            self._lock = threading.Lock()
            self._state = {"ticks": 0}

    def ticker_tick(self):
        """Handle periodic background tasks."""
        with self._lock:
            self._state["ticks"] += 1
            ticks = self._state["ticks"]
        self._lg.info(f"Background task executed (tick {ticks})")

    def do_GET(self, instance):
        """Handle HTTP requests."""
        with self._lock:
            ticks = self._state["ticks"]
        instance.send_response(200)
        instance.send_header("Content-type", "application/json")
        instance.end_headers()
        instance.wfile.write(json.dumps({"status": "ok", "ticks": ticks}).encode())


# Create and run server with ticker
handler = MyTickerHandler(logger)
server = TCPServer(logger, 8080, handler, handler)
server.run()  # Runs in multiprocessing mode
```

**Mode Selection:**

- Multiprocessing mode is automatically used when a `Ticker` instance is passed to `TCPServer`
- Single-process mode is used when `ticker=None`
- The `manager` parameter in `ticker_start` is `None` in single-process mode and a
  `multiprocessing.Manager()` instance in multiprocessing mode
- Inheritance order matters for MRO: `Ticker, TickerHandler, HTTPRequestHandler`

## REST API Example

```python
import json


class ApiHandler(HTTPRequestHandler):
    def do_GET(self, instance):
        """Handle GET requests."""
        instance.send_response(200)
        instance.send_header("Content-type", "application/json")
        instance.end_headers()
        instance.wfile.write(b'{"message": "Hello, World!"}')

    def do_POST(self, instance):
        """Handle POST requests."""
        if "Content-Length" not in instance.headers:
            instance.send_response(411)  # Length Required
            instance.end_headers()
            return

        content_length = int(instance.headers["Content-Length"])
        post_data = instance.rfile.read(content_length)

        # Process post_data...
        data = json.loads(post_data)

        instance.send_response(200)
        instance.send_header("Content-type", "application/json")
        instance.end_headers()
        instance.wfile.write(b'{"status": "processed"}')
```

## Exception Classes

```python
from appinfra.net import (
    ServerError,  # Base exception for server errors
    ServerStartupError,  # Server failed to start
    ServerShutdownError,  # Server failed to shutdown gracefully
    HandlerError,  # Request handler error
)
```

**Error Handling:**

```python
from appinfra.net import TCPServer, ServerStartupError

try:
    server = TCPServer(logger, 8080, handler)
    server.run()
except ServerStartupError as e:
    logger.error(f"Failed to start server: {e}")
```

## Thread Safety

- **Single-process mode**: Uses threading for concurrent request handling
- **Multiprocessing mode**: Uses `multiprocessing.Manager()` for shared state between processes
- **Request handling**: Each request is handled in its own thread/process context

## Graceful Shutdown

The server handles shutdown signals (SIGTERM, SIGINT) for clean resource cleanup:

```python
server = TCPServer(logger, 8080, handler)
# Server runs until interrupted
exit_code = server.run()
# Resources are cleaned up automatically
```

## Integration with AppBuilder

For FastAPI-style applications, use the FastAPI integration instead:

```python
from appinfra.app.fastapi import FastAPIBuilder

server = FastAPIBuilder("api").with_config(config).with_port(8000).build()
```

See [FastAPI Integration](fastapi.md) for subprocess-based FastAPI servers.

## See Also

- [FastAPI Integration](fastapi.md) - FastAPI with subprocess isolation
- [Time & Scheduling](time.md) - Ticker for background tasks
- [Application Framework](app.md) - Full application lifecycle
