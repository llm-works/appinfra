# infra/net Package

The `infra/net` package provides networking utilities for building HTTP servers with background processing capabilities. It offers a flexible TCP server implementation that can run in single-process or multiprocessing modes, with seamless integration with the application's ticker system.

## Overview

The package is designed for applications that need to serve HTTP requests while performing background tasks, such as:
- Web APIs with periodic data updates
- Monitoring services with health checks
- Data processing servers with background workers
- Real-time applications with ticker-based updates

## Key Features

- **Dual Execution Modes**: Single-process and multiprocessing support
- **Ticker Integration**: Seamless integration with periodic task execution
- **HTTP Request Handling**: Custom request processing with delegation
- **Graceful Shutdown**: Proper cleanup and resource management
- **Comprehensive Logging**: Deep integration with framework's logging system
- **Error Handling**: Robust error handling and recovery mechanisms
- **Thread Safety**: Designed for concurrent request handling

## Architecture

### Core Components

1. **`Server`**: Main TCP server with flexible execution modes
2. **`_Server`**: Internal TCP server implementation extending `socketserver.TCPServer`
3. **`RequestHandler`**: HTTP request handler with delegation to custom handlers
4. **Exception Classes**: Custom exceptions for error handling

### Execution Modes

#### Single-Process Mode
- Runs everything in the current process
- Suitable for simple applications
- Uses threading for concurrency
- Automatic ticker integration if handler supports it

#### Multiprocessing Mode
- Runs ticker in a separate process
- Better isolation and fault tolerance
- Uses `multiprocessing.Manager()` for shared state
- Automatic process cleanup on shutdown

## Usage Examples

### Simple HTTP Server

```python
from appinfra.net import TCPServer, HTTPRequestHandler
from appinfra.log import LoggerFactory, LogConfig


class MyHandler(HTTPRequestHandler):
    def do_GET(self, instance):
        instance.send_response(200)
        instance.send_header("Content-type", "text/html")
        instance.end_headers()
        instance.wfile.write(b"Hello, World!")


# Create and run server
config = LogConfig.from_params("info")
lg = LoggerFactory.create_root(config)
server = TCPServer(lg, 8080, MyHandler())
server.run()
```

### Server with Background Ticker

```python
from appinfra.net import TCPServer, HTTPRequestHandler
from appinfra.time import Ticker, TickerHandler
from appinfra.log import LoggerFactory, LogConfig


class MyTickerHandler(Ticker, TickerHandler, HTTPRequestHandler):
    def __init__(self, lg):
        self._lg = lg
        self._ticks = 0
        super().__init__(self, secs=5)  # Tick every 5 seconds

    def ticker_start(self, manager=None):
        """Initialize shared state."""
        if manager is not None:
            self._lock = manager.Lock()
            self._msg = manager.dict()
        else:
            import threading

            self._lock = threading.Lock()
            self._msg = {"started": True}

    def ticker_tick(self):
        """Handle periodic tasks."""
        self._ticks += 1
        self._lg.info(f"Background task executed (tick {self._ticks})")

    def do_GET(self, instance):
        """Handle HTTP requests."""
        instance.send_response(200)
        instance.send_header("Content-type", "application/json")
        instance.end_headers()
        instance.wfile.write(
            json.dumps({"status": "ok", "ticks": self._ticks}).encode()
        )


# Create and run server with ticker
config = LogConfig.from_params("info")
lg = LoggerFactory.create_root(config)
handler = MyTickerHandler(lg)
server = TCPServer(lg, 8080, handler, handler)
server.run()  # Runs in multiprocessing mode
```

### Custom Request Handling

```python
class ApiHandler(HTTPRequestHandler):
    def do_GET(self, instance):
        """Handle GET requests."""
        instance.send_response(200)
        instance.send_header("Content-type", "application/json")
        instance.end_headers()
        instance.wfile.write(b'{"message": "Hello, World!"}')

    def do_POST(self, instance):
        """Handle POST requests."""
        content_length = int(instance.headers["Content-Length"])
        post_data = instance.rfile.read(content_length)

        # Process post_data...

        instance.send_response(200)
        instance.send_header("Content-type", "application/json")
        instance.end_headers()
        instance.wfile.write(b'{"status": "processed"}')
```

## API Reference

### Server Class

```python
class Server:
    def __init__(self, lg, port, handler, ticker=None):
        """
        Initialize the TCP server.
        
        Args:
            lg: Logger instance for server operations
            port (int): Port number to listen on
            handler: Request handler instance
            ticker: Optional ticker for background processing
        """
    
    def run(self):
        """
        Run the TCP server.
        
        Chooses between single-process and multiprocessing mode
        based on whether a ticker is provided.
        
        Returns:
            int: Exit code (0 for success)
        """
```

### RequestHandler Class

```python
class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        """Handle HTTP GET requests."""
        
    def do_HEAD(self):
        """Handle HTTP HEAD requests."""
        
    def log_message(self, format, *args, **kwargs):
        """Log HTTP request messages using application's logging system."""
```

### Exception Classes

```python
class ServerError(Exception):
    """Base exception for server-related errors."""


class ServerStartupError(ServerError):
    """Raised when server fails to start."""


class ServerShutdownError(ServerError):
    """Raised when server fails to shutdown gracefully."""


class HandlerError(ServerError):
    """Raised when request handler encounters an error."""
```

## Error Handling

The package provides comprehensive error handling:

- **Startup Errors**: Validation of parameters and initialization failures
- **Runtime Errors**: HTTP server errors and ticker failures
- **Shutdown Errors**: Graceful cleanup failures
- **Handler Errors**: Request processing errors with proper HTTP responses

All errors are logged using the application's logging system and include detailed tracebacks for debugging.

## Thread Safety

The server is designed to be thread-safe when used correctly:

- **Single-Process Mode**: Uses threading for concurrent request handling
- **Multiprocessing Mode**: Uses separate processes with shared state via `multiprocessing.Manager()`
- **Request Handling**: Each request is handled in its own thread/process context

## Integration Points

### Framework Integration
- **Logging**: Deep integration with framework's structured logging system
- **Time System**: Integration with `Ticker` and `TickerHandler` interfaces
- **Configuration**: Can integrate with framework's configuration system

### External Dependencies
- **Standard Library**: Primarily uses Python standard library (`socketserver`, `http.server`, `multiprocessing`)
- **Minimal Dependencies**: Low external dependency footprint
- **Cross-platform**: Works across different operating systems

## Testing

The package includes comprehensive test coverage:

- **Unit Tests**: Individual component testing (`tcp_test.py`, `http_test.py`)
- **Integration Tests**: End-to-end testing (`integration_test.py`)
- **Error Handling Tests**: Error scenarios and recovery
- **Concurrency Tests**: Thread safety and multiprocessing isolation
- **Performance Tests**: Load testing and performance validation

Run tests with:
```bash
source ~/.venv/bin/activate
timeout 30 python -m unittest infra.net.tcp_test -v
timeout 30 python -m unittest infra.net.http_test -v
timeout 30 python -m unittest infra.net.integration_test -v
```

## Performance Considerations

- **Single-Process Mode**: Lower overhead, suitable for moderate loads
- **Multiprocessing Mode**: Better isolation, suitable for high loads
- **Request Handling**: Efficient delegation to custom handlers
- **Resource Management**: Proper cleanup and resource management

## Security Considerations

- **Input Validation**: Validate all input parameters
- **Error Handling**: Don't expose sensitive information in error messages
- **Access Control**: Implement proper authentication and authorization
- **HTTPS Support**: Consider SSL/TLS for production deployments

## Future Enhancements

Potential areas for future development:

- **SSL/TLS Support**: HTTPS support for secure connections
- **WebSocket Support**: Real-time communication capabilities
- **Middleware Support**: Request/response processing pipeline
- **Configuration**: More flexible server configuration options
- **Metrics**: Built-in performance and health metrics
- **Load Balancing**: Support for multiple server instances

## Contributing

When contributing to the net package:

1. **Follow the existing code style and patterns**
2. **Add comprehensive tests for new functionality**
3. **Update documentation for API changes**
4. **Consider backward compatibility**
5. **Test both single-process and multiprocessing modes**

## License

This package is part of the infra framework and follows the same licensing terms.
