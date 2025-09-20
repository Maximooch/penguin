# Chrome Debugging and Process Management in Penguin

This document describes the advanced Chrome debugging and process management capabilities in Penguin.

## Chrome DevTools Protocol Debugger

The Chrome debugger provides direct access to Chrome's debugging capabilities through the Chrome DevTools Protocol (CDP) over WebSockets. This implementation bypasses the need for ChromeDriver and interacts directly with Chrome's debugging interface.

### Getting Started

1. Start Chrome with the remote debugging port enabled:

```bash
google-chrome --remote-debugging-port=9222 --remote-allow-origins=*
```

2. Import and use the `ChromeDebugger` class:

```python
from penguin.tools.chrome_debugger import ChromeDebugger

# Initialize and connect
debugger = ChromeDebugger(host="localhost", port=9222)
await debugger.connect()

# Use CDP methods
await debugger.navigate("https://example.com")
screenshot_path = await debugger.take_screenshot()

# Clean up when done
await debugger.disconnect()
```

### Key Features

- **Direct CDP Access**: Communicate with Chrome directly via WebSockets
- **Domain Management**: Enable specific CDP domains as needed
- **Event Handling**: Register custom handlers for browser events
- **JavaScript Evaluation**: Execute JavaScript in the browser context
- **Screenshots**: Capture viewport or full-page screenshots
- **Console Monitoring**: Track console messages
- **Network Monitoring**: Monitor requests and responses
- **JavaScript Debugging**: Set breakpoints and inspect execution

### Example Use Cases

- Automated web testing
- Taking snapshots of web pages
- Scraping dynamic websites
- Monitoring network traffic
- Debugging complex web applications

### API Overview

- `connect()`: Connect to a Chrome debugging target
- `disconnect()`: Disconnect from Chrome
- `enable_domain(domain)`: Enable a CDP domain
- `execute(method, params)`: Execute a CDP method
- `register_event_handler(event, handler)`: Register a handler for events
- `navigate(url)`: Navigate to a URL
- `take_screenshot(filepath, full_page)`: Capture a screenshot
- `get_console_logs()`: Get console logs
- `evaluate_javascript(expression)`: Evaluate JavaScript code

See the `examples.py` file for detailed examples of each feature.

## Enhanced Process Manager

The `EnhancedProcessManager` provides improved process management with PTY support, structured communication, better buffer management, and process monitoring.

### Key Features

1. **PTY Support**: Creates true terminal emulation for more accurate process interaction
2. **Structured Communication**: Parses JSON output for structured data exchange
3. **Improved Buffer Management**: Better handling of process output with size limits
4. **Process Monitoring**: Health checks and automatic recovery for crashed processes
5. **Terminal Resizing**: Adjust terminal dimensions for processes
6. **Interactive Mode**: Enter and exit interactive mode with processes
7. **Output Callbacks**: Register callbacks for process output

### Usage Example

```python
from penguin.utils.enhanced_process_manager import EnhancedProcessManager

# Initialize the process manager
process_manager = EnhancedProcessManager()

# Start a process with PTY support
await process_manager.start_process(
    name="example",
    command="python -i",  # Interactive Python shell
    use_pty=True,
    structured_output=False,
    auto_restart=True
)

# Enter interactive mode
await process_manager.enter_process("example")

# Send commands
await process_manager.send_command("example", "print('Hello, world!')")

# Get process output
output = await process_manager.get_output("example")
print(output)

# Exit interactive mode
await process_manager.exit_process("example")

# Stop the process
await process_manager.stop_process("example")

# Clean up
process_manager.close()
```

### Use Cases

- Running interactive command-line tools
- Managing long-running processes
- Capturing structured output from processes
- Creating terminal-based user interfaces
- Automating interactive CLI workflows

## Choosing the Right Tool

- **Use ChromeDebugger** when you need precise control over a web browser, DOM manipulation, JavaScript execution, or network monitoring.
- **Use EnhancedProcessManager** when you need to interact with command-line tools, REPL environments, or any process that requires a terminal interface.

## Additional Resources

- [Chrome DevTools Protocol Documentation](https://chromedevtools.github.io/devtools-protocol/)
- [Python PTY Module Documentation](https://docs.python.org/3/library/pty.html) 