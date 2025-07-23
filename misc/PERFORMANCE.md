# Penguin Performance Optimizations

This document explains the performance improvements implemented in Penguin, particularly around startup time optimization and profiling capabilities.

## Fast Startup Mode

### Overview

Penguin's fast startup mode significantly reduces initialization time by deferring heavy operations until they're actually needed. This is particularly beneficial for:

- CLI usage where you need quick responses
- Development environments where you frequently restart Penguin
- Automated scripts that don't use memory-intensive features

### How It Works

**Normal Startup:**
1. Initialize core components
2. Initialize all tools immediately
3. Start memory provider
4. Index all workspace files (notes, conversations)
5. Load browser tools
6. Ready for use

**Fast Startup:**
1. Initialize core components
2. Initialize only lightweight tools
3. Defer memory provider initialization
4. Defer file indexing until first memory search
5. Defer browser tools until first browser operation
6. Ready for use (much faster!)

### Usage

#### Via Command Line

```bash
# Enable fast startup for this session
penguin --fast-startup

# Run performance test to see the difference
penguin perf-test

# Run with fast startup in interactive mode
penguin --fast-startup chat
```

#### Via Configuration File

Create or edit your `config.yml`:

```yaml
# Performance optimizations
performance:
  fast_startup: true  # Enable by default

# Rest of your configuration...
model:
  default: "anthropic/claude-3-5-sonnet-20240620"
  # ...
```

#### Programmatically

```python
from penguin.core import PenguinCore

# Fast startup
core = await PenguinCore.create(fast_startup=True)

# Normal startup  
core = await PenguinCore.create(fast_startup=False)
```

### Performance Impact

Typical performance improvements:

- **2-5x faster startup time** depending on workspace size
- **Memory indexing deferred** until first search operation
- **Browser tools deferred** until first browser interaction
- **Immediate CLI responsiveness** for non-memory operations

### Trade-offs

**Benefits:**
- Much faster startup time
- Lower initial memory usage
- Better development experience
- Ideal for quick tasks

**Considerations:**
- First memory search may be slower (includes indexing time)
- Memory tools not immediately available
- Background indexing happens on first memory tool use

## Profiling System

### Built-in Performance Tracking

Penguin includes a comprehensive profiling system to help identify performance bottlenecks:

```python
from penguin.utils.profiling import enable_profiling, print_startup_report

# Enable profiling
enable_profiling()

# ... use Penguin ...

# Print detailed performance report
print_startup_report()
```

### Performance Testing

Use the built-in performance test command:

```bash
# Run startup performance benchmark
penguin perf-test

# Run multiple iterations for better accuracy
penguin perf-test --iterations 5

# Run test without detailed report
penguin perf-test --no-report
```

### Profiling Output

The profiling system tracks:

- **Startup phases** with timing breakdown
- **Component initialization** times
- **Memory usage** patterns
- **Async task** lifecycle
- **Tool loading** performance

Example output:
```
=== Penguin Startup Performance Report ===
Total operations tracked: 15

Startup Phases:
  Load environment: 0.0045s (2.1%)
  Setup logging: 0.0123s (5.8%)
  Load configuration: 0.0234s (11.0%)
  Create model config: 0.0156s (7.3%)
  Initialize API client: 0.0445s (20.9%)
  Create tool manager: 0.1123s (52.7%)
  Create core instance: 0.0012s (0.6%)
  TOTAL STARTUP: 0.2138s

Slowest Operations:
  ToolManager.memory_provider_init: 0.0890s (avg: 0.0890s, count: 1)
  ToolManager.lightweight_init: 0.0123s (avg: 0.0123s, count: 1)
```

## Best Practices

### When to Use Fast Startup

**Recommended for:**
- CLI-first workflows
- Development and testing
- Quick tasks and automation
- Environments with limited resources

**Consider normal startup for:**
- Long-running interactive sessions
- Heavy memory search workloads
- Production deployments with stable uptime

### Configuration Recommendations

For development:
```yaml
performance:
  fast_startup: true

diagnostics:
  enabled: true  # Enable for performance monitoring
```

For production:
```yaml
performance:
  fast_startup: false  # Prefer immediate availability

diagnostics:
  enabled: false  # Disable for performance
```

### Memory Tool Usage

With fast startup enabled:

```python
# First memory search triggers indexing
# (will be slower than subsequent searches)
result = await core.tool_manager.perform_memory_search("query")

# Subsequent searches are fast
result2 = await core.tool_manager.perform_memory_search("another query")
```

### Monitoring Performance

```python
# Check memory provider status
status = core.get_memory_provider_status()
print(f"Memory provider: {status}")

# Get startup statistics
stats = core.get_startup_stats()
print(f"Startup stats: {stats}")

# Print comprehensive performance report
core.print_startup_report()
```

## Troubleshooting

### Performance Issues

1. **Check if fast startup is enabled:**
   ```bash
   penguin perf-test
   ```

2. **Monitor background tasks:**
   ```python
   status = core.get_memory_provider_status()
   print(status["indexing_task_running"])
   ```

3. **Enable diagnostics for detailed analysis:**
   ```yaml
   diagnostics:
     enabled: true
     log_to_file: true
     log_path: "${paths.logs}/performance.log"
   ```

### Common Issues

**Slow memory searches:** First search after startup includes indexing time. Subsequent searches should be fast.

**Memory tools not working:** Check if memory provider initialization failed:
```python
provider_status = core.get_memory_provider_status()
if provider_status["status"] == "disabled":
    print("Memory provider is disabled in configuration")
```

**Background indexing stuck:** Check async task status:
```python
status = core.get_memory_provider_status()
if status.get("indexing_task_status", {}).get("exception"):
    print(f"Indexing failed: {status['indexing_task_status']['exception']}")
```

## Future Improvements

- **Incremental indexing:** Only index changed files
- **Parallel tool loading:** Load tools concurrently
- **Smart preloading:** Predict and preload likely-needed tools
- **Cache optimization:** Better caching of frequently used data
- **Streaming initialization:** Progressive loading with immediate partial functionality 