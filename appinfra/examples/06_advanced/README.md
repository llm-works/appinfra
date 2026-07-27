# Advanced Topics

Advanced patterns and utilities in the infra framework.

## Examples

### generator_usage_example.py
Generator methods for efficient iteration.

**What you'll learn:**
- Handler type discovery
- Iterating through handlers
- Memory-efficient iteration patterns
- Lazy evaluation with generators

**Run:**
```bash
~/.venv/bin/python examples/06_advanced/generator_usage_example.py
```

**Key concepts:**
- `HandlerFactory.iter_supported_types()` - Discover handler types
- `HandlerRegistry.iter_handlers()` - Iterate all handlers
- `HandlerRegistry.iter_enabled_handlers()` - Iterate enabled only
- Memory efficiency for large collections

---

### tcp_server.py
TCP server with background ticker.

**What you'll learn:**
- TCP server setup
- HTTP request handling
- Combining server with ticker
- Threading patterns
- Graceful shutdown

**Run:**
```bash
~/.venv/bin/python examples/06_advanced/tcp_server.py
```

**Key concepts:**
- `TCPServer` from `infra.net`
- Request handler implementation
- Ticker integration
- Multi-threading considerations

---

### ticker_standalone.py
Standalone ticker usage without app framework.

**What you'll learn:**
- Using Ticker independently
- Scheduled vs continuous modes
- Background task patterns
- Direct ticker API

**Run:**
```bash
~/.venv/bin/python examples/06_advanced/ticker_standalone.py
```

**Key concepts:**
- `Ticker` class from `infra.time`
- Handler pattern for periodic tasks
- Start/stop lifecycle
- Standalone usage (no App required)

---

## Advanced Patterns

### Generator Pattern
Use generators for memory-efficient iteration:
```python
# Memory efficient - yields one at a time
for handler in registry.iter_enabled_handlers():
    process(handler)

# Memory inefficient - loads all into memory
handlers = list(registry.get_all_handlers())
for handler in handlers:
    process(handler)
```

### Server Pattern
Combine servers with tickers for background tasks:
```python
class MyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Handle HTTP requests
        pass


class TickerHandler:
    def handle(self):
        # Background task
        pass


# Server handles requests, ticker does background work
server = TCPServer(("localhost", 8000), MyHandler)
ticker = Ticker(1.0, TickerHandler())
```

### Standalone Utilities
Use framework components independently:
```python
# Ticker without App
ticker = Ticker(interval=5.0, handler=my_handler)
ticker.start()

# Logger without App
logger = LoggingBuilder("standalone").console_handler().build()

# Config without App
config = Config("etc/infra.yaml")
```

## Performance Considerations

### Generators
- **Use when**: Large collections, memory constraints
- **Don't use when**: Need random access or length
- **Memory**: O(1) vs O(n) for lists

### Threading
- **TCP server**: Runs in separate thread
- **Ticker**: Can run in separate thread
- **GIL**: Python GIL limits true parallelism
- **Recommendation**: Use multiprocessing for CPU-bound tasks

### Resource Management
- **Always cleanup**: Use try/finally or context managers
- **Graceful shutdown**: Stop tickers before exit
- **Connection pooling**: Reuse expensive resources

## Best Practices

1. **Generators for large datasets** - Memory efficient iteration
2. **Graceful shutdown** - Clean up resources properly
3. **Error handling** - Wrap server/ticker in try/except
4. **Logging** - Log server requests and ticker executions
5. **Monitoring** - Track performance metrics

## Common Patterns

### Background Task with Server
```python
# Start both server and background task
server_thread = threading.Thread(target=server.serve_forever)
server_thread.start()

ticker.start()

# Graceful shutdown
ticker.stop()
server.shutdown()
server_thread.join()
```

### Periodic Cleanup Task
```python
class CleanupHandler:
    def handle(self):
        cleanup_old_files()
        purge_expired_sessions()


ticker = Ticker(interval=3600.0, handler=CleanupHandler())  # Every hour
ticker.start()
```

### Discovery Pattern
```python
# Discover available components
for handler_type in HandlerFactory.iter_supported_types():
    print(f"Available: {handler_type}")

# Load only what you need
for handler in registry.iter_enabled_handlers():
    logger.addHandler(handler.create_handler())
```

## Troubleshooting

### Ticker not stopping
- Call `ticker.stop()` explicitly
- Check for blocking operations in handler
- Use daemon threads for background tasks

### Server port already in use
```bash
# Find process using port
lsof -i :8000

# Kill process
kill -9 <PID>
```

### Memory growing over time
- Check for generator usage
- Verify cleanup in handlers
- Monitor with `tracemalloc` or `memory_profiler`

## Next Steps

After mastering advanced topics:
- Read framework source code in `infra/`
- Contribute improvements or new examples
- Build production applications with the framework

## Related Documentation

- [Time Utilities](../../infra/time/) - Ticker, Scheduler, Delta source code
- [Network](../../infra/net/) - TCP/HTTP server source code
- [Main README](../README.md) - Full examples index
