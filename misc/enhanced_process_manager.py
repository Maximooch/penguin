"""Enhanced Process Manager for Penguin with PTY support.

This module provides an improved process manager that uses pseudoterminals
for more realistic terminal interactions, adds structured communication,
better buffer management, and process monitoring capabilities.
"""

import asyncio
import pty
import os
import signal
import json
import logging
import shlex
import fcntl
import termios
import struct
import time
import psutil
from typing import Dict, List, Optional, Any, Tuple, Callable

logger = logging.getLogger(__name__)

class ProcessError(Exception):
    """Base exception for process errors."""
    pass

class EnhancedProcessManager:
    """Enhanced process manager with PTY support.
    
    This class manages subprocess execution with the following improvements:
    
    1. Uses PTY for true terminal emulation
    2. Supports structured (JSON) and raw communication modes
    3. Improved buffer management
    4. Process health monitoring and automatic recovery
    """
    
    def __init__(self):
        """Initialize the process manager."""
        self.processes: Dict[str, Dict[str, Any]] = {}
        self.active_processes: Dict[str, Dict[str, Any]] = {}
        self.event_loop = asyncio.get_event_loop()
        self.monitor_task = None
        
        # Start process monitoring task
        self._start_monitoring()
    
    def _start_monitoring(self):
        """Start background monitoring of processes."""
        self.monitor_task = asyncio.create_task(self._monitor_processes())
    
    async def _monitor_processes(self):
        """Periodically check process health and handle issues."""
        try:
            while True:
                for name, proc_info in list(self.processes.items()):
                    # Skip check if process is not meant to be monitored
                    if not proc_info.get("monitor", True):
                        continue
                        
                    pid = proc_info.get("pid")
                    if pid is None:
                        continue
                    
                    # Check if process is still running
                    try:
                        process = psutil.Process(pid)
                        if not process.is_running():
                            logger.warning(f"Process '{name}' (PID {pid}) is no longer running")
                            
                            # Handle auto-restart if configured
                            if proc_info.get("auto_restart", False):
                                logger.info(f"Auto-restarting process '{name}'")
                                command = proc_info.get("command")
                                if command:
                                    await self.stop_process(name)
                                    await self.start_process(
                                        name, 
                                        command, 
                                        use_pty=proc_info.get("use_pty", True),
                                        auto_restart=True
                                    )
                    except psutil.NoSuchProcess:
                        logger.warning(f"Process '{name}' (PID {pid}) no longer exists")
                        
                        # Clean up the dead process
                        if name in self.active_processes:
                            await self.exit_process(name)
                
                # Sleep before next check
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            # Task was cancelled, exit gracefully
            logger.debug("Process monitor task cancelled")
        except Exception as e:
            logger.error(f"Error in process monitor: {str(e)}")
    
    async def start_process(
        self, 
        name: str, 
        command: str, 
        env: Dict[str, str] = None,
        use_pty: bool = True,
        cwd: str = None,
        structured_output: bool = False,
        buffer_size: int = 10240,
        auto_restart: bool = False,
        terminal_size: Tuple[int, int] = (24, 80)
    ) -> str:
        """Start a process with optional PTY support.
        
        Args:
            name: Name to identify the process
            command: Command to execute
            env: Optional environment variables
            use_pty: Whether to use a pseudoterminal
            cwd: Working directory for the process
            structured_output: Whether to attempt parsing output as JSON
            buffer_size: Size of the output buffer
            auto_restart: Whether to automatically restart the process if it dies
            terminal_size: Terminal dimensions as (rows, cols)
            
        Returns:
            Status message
        """
        try:
            # Clean up any existing process with the same name
            if name in self.processes:
                await self.stop_process(name)
            
            if use_pty:
                # Parse command for proper argument handling
                args = shlex.split(command)
                
                # Create PTY
                master_fd, slave_fd = pty.openpty()
                
                # Set terminal size
                rows, cols = terminal_size
                term_size = struct.pack('HHHH', rows, cols, 0, 0)
                fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, term_size)
                
                # Create environment
                process_env = os.environ.copy()
                if env:
                    process_env.update(env)
                
                # Start process
                pid = os.fork()
                if pid == 0:
                    # Child process
                    try:
                        os.close(master_fd)
                        os.setsid()
                        
                        # Duplicate the slave fd to stdin/stdout/stderr
                        os.dup2(slave_fd, 0)
                        os.dup2(slave_fd, 1)
                        os.dup2(slave_fd, 2)
                        
                        if slave_fd > 2:
                            os.close(slave_fd)
                            
                        # Change directory if specified
                        if cwd:
                            os.chdir(cwd)
                        
                        # Execute command
                        os.execvpe(args[0], args, process_env)
                    except Exception as e:
                        print(f"Error in child process: {str(e)}")
                        os._exit(1)
                else:
                    # Parent process
                    os.close(slave_fd)
                    
                    # Make master_fd non-blocking
                    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
                    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
                    
                    # Create reader and writer for the master fd
                    reader = asyncio.StreamReader()
                    protocol = asyncio.StreamReaderProtocol(reader)
                    
                    # Use low-level transport-protocol API
                    transport, _ = await self.event_loop.connect_read_pipe(
                        lambda: protocol, os.fdopen(master_fd, 'rb')
                    )
                    
                    # Store process info
                    self.processes[name] = {
                        "pid": pid,
                        "master_fd": master_fd,
                        "transport": transport,
                        "reader": reader,
                        "command": command,
                        "start_time": time.time(),
                        "use_pty": use_pty,
                        "structured_output": structured_output,
                        "monitor": True,
                        "auto_restart": auto_restart,
                        "buffer": bytearray(),
                        "buffer_size": buffer_size
                    }
                    
                    logger.info(f"Process '{name}' started with PID {pid} using PTY")
                    return f"Process '{name}' started with PID {pid} using PTY"
            else:
                # Use subprocess without PTY
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    stdin=asyncio.subprocess.PIPE,
                    env=env if env else None,
                    cwd=cwd
                )
                
                # Store process info
                self.processes[name] = {
                    "pid": process.pid,
                    "process": process,
                    "command": command,
                    "start_time": time.time(),
                    "use_pty": False,
                    "structured_output": structured_output,
                    "monitor": True,
                    "auto_restart": auto_restart,
                    "buffer": bytearray(),
                    "buffer_size": buffer_size
                }
                
                logger.info(f"Process '{name}' started with PID {process.pid}")
                return f"Process '{name}' started with PID {process.pid}"
        except Exception as e:
            logger.error(f"Error starting process '{name}': {str(e)}")
            return f"Error starting process '{name}': {str(e)}"
    
    async def stop_process(self, name: str, timeout: float = 5.0) -> str:
        """Stop a running process.
        
        Args:
            name: Name of the process to stop
            timeout: Seconds to wait for graceful termination before killing
            
        Returns:
            Status message
        """
        if name not in self.processes:
            return f"Process '{name}' not found"
        
        # First, exit interactive mode if active
        if name in self.active_processes:
            await self.exit_process(name)
        
        proc_info = self.processes[name]
        
        try:
            pid = proc_info.get("pid")
            use_pty = proc_info.get("use_pty", False)
            
            if use_pty:
                # Close the transport
                if "transport" in proc_info:
                    proc_info["transport"].close()
                
                # Send SIGTERM to the process group
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except ProcessLookupError:
                    # Process already terminated
                    pass
                
                # Wait for termination
                try:
                    # Poll for process termination
                    deadline = time.time() + timeout
                    while time.time() < deadline:
                        try:
                            # Check if process exists
                            os.kill(pid, 0)
                            # Process still exists, wait a bit
                            await asyncio.sleep(0.1)
                        except ProcessLookupError:
                            # Process terminated
                            break
                    
                    # If still running, send SIGKILL
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except ProcessLookupError:
                        # Process already terminated
                        pass
                except Exception as e:
                    logger.error(f"Error waiting for process termination: {str(e)}")
                
                # Close the master fd
                if "master_fd" in proc_info:
                    try:
                        os.close(proc_info["master_fd"])
                    except OSError:
                        pass
            else:
                # Non-PTY subprocess
                process = proc_info.get("process")
                if process:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=timeout)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
            
            # Remove process from tracking
            del self.processes[name]
            return f"Process '{name}' stopped"
            
        except Exception as e:
            logger.error(f"Error stopping process '{name}': {str(e)}")
            # Still remove from tracking in case of error
            if name in self.processes:
                del self.processes[name]
            return f"Error stopping process '{name}': {str(e)}"
    
    async def get_process_status(self, name: str) -> Dict[str, Any]:
        """Get detailed status for a process.
        
        Args:
            name: Name of the process
            
        Returns:
            Dictionary with status information
        """
        if name not in self.processes:
            return {"error": f"Process '{name}' not found"}
        
        proc_info = self.processes[name]
        pid = proc_info.get("pid")
        
        try:
            # Get process details via psutil
            process = psutil.Process(pid)
            
            return {
                "name": name,
                "pid": pid,
                "running": process.is_running(),
                "status": process.status(),
                "cpu_percent": process.cpu_percent(interval=0.1),
                "memory_percent": process.memory_percent(),
                "start_time": proc_info.get("start_time"),
                "command": proc_info.get("command"),
                "uptime": time.time() - proc_info.get("start_time", time.time()),
                "using_pty": proc_info.get("use_pty", False),
                "auto_restart": proc_info.get("auto_restart", False),
                "interactive": name in self.active_processes
            }
        except psutil.NoSuchProcess:
            return {
                "name": name,
                "pid": pid,
                "running": False,
                "status": "terminated",
                "command": proc_info.get("command"),
                "start_time": proc_info.get("start_time"),
                "using_pty": proc_info.get("use_pty", False),
                "auto_restart": proc_info.get("auto_restart", False),
                "interactive": name in self.active_processes
            }
        except Exception as e:
            logger.error(f"Error getting status for process '{name}': {str(e)}")
            return {"error": f"Error getting status: {str(e)}"}
    
    async def list_processes(self) -> List[Dict[str, Any]]:
        """List all managed processes with their basic status.
        
        Returns:
            List of process information dictionaries
        """
        result = []
        for name in self.processes:
            status = await self.get_process_status(name)
            result.append(status)
        return result
    
    async def enter_process(self, name: str) -> bool:
        """Enter interactive mode with a process.
        
        Args:
            name: Name of the process to interact with
            
        Returns:
            True if successful, False otherwise
        """
        if name not in self.processes:
            logger.error(f"Process '{name}' not found")
            return False
        
        if name in self.active_processes:
            logger.warning(f"Already in interactive mode with process '{name}'")
            return True
        
        proc_info = self.processes[name]
        use_pty = proc_info.get("use_pty", False)
        
        try:
            if use_pty:
                # PTY process
                reader = proc_info.get("reader")
                if not reader:
                    logger.error(f"Reader not found for process '{name}'")
                    return False
                
                # Store interactive session info
                self.active_processes[name] = {
                    "reader": reader,
                    "buffer": bytearray(),
                    "output_callback": None
                }
                
                # Start reading in the background
                asyncio.create_task(self._read_pty_output(name))
                logger.info(f"Entered interactive mode with process '{name}'")
                return True
            else:
                # Standard subprocess
                process = proc_info.get("process")
                if not process:
                    logger.error(f"Process object not found for '{name}'")
                    return False
                
                # Store interactive session info
                self.active_processes[name] = {
                    "process": process,
                    "buffer": bytearray(),
                    "output_callback": None
                }
                
                # Start reading in the background
                asyncio.create_task(self._read_subprocess_output(name))
                logger.info(f"Entered interactive mode with process '{name}'")
                return True
        except Exception as e:
            logger.error(f"Error entering process '{name}': {str(e)}")
            return False
    
    async def register_output_callback(
        self, 
        name: str, 
        callback: Callable[[str], None]
    ) -> bool:
        """Register a callback for process output.
        
        Args:
            name: Name of the process
            callback: Function to call with each output chunk
            
        Returns:
            True if successful, False otherwise
        """
        if name not in self.active_processes:
            logger.error(f"Not in interactive mode with process '{name}'")
            return False
        
        self.active_processes[name]["output_callback"] = callback
        return True
    
    async def _read_pty_output(self, name: str) -> None:
        """Background task to read output from a PTY process.
        
        Args:
            name: Name of the process
        """
        try:
            if name not in self.processes or name not in self.active_processes:
                logger.error(f"Process '{name}' not found for reading")
                return
            
            proc_info = self.processes[name]
            active_info = self.active_processes[name]
            reader = proc_info.get("reader")
            buffer = active_info.get("buffer", bytearray())
            structured = proc_info.get("structured_output", False)
            buffer_size = proc_info.get("buffer_size", 10240)
            
            while name in self.active_processes:
                try:
                    # Read a chunk of data
                    chunk = await reader.read(1024)
                    
                    if not chunk:
                        # EOF reached
                        logger.debug(f"EOF reached for process '{name}'")
                        break
                    
                    # Append to buffer, respecting size limit
                    buffer.extend(chunk)
                    if len(buffer) > buffer_size:
                        # Trim buffer from the beginning
                        buffer = buffer[-buffer_size:]
                    
                    # Update buffer in active_info
                    active_info["buffer"] = buffer
                    
                    # Process structured output if enabled
                    if structured:
                        await self._process_structured_output(name, chunk)
                    
                    # Call output callback if registered
                    callback = active_info.get("output_callback")
                    if callback:
                        try:
                            await callback(chunk.decode("utf-8", errors="replace"))
                        except Exception as e:
                            logger.error(f"Error in output callback: {str(e)}")
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error reading from PTY: {str(e)}")
                    await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in PTY reader task: {str(e)}")
        finally:
            # Clean up if needed
            if name in self.active_processes:
                if not self.active_processes.get(name, {}).get("keep_open", False):
                    await self.exit_process(name)
    
    async def _read_subprocess_output(self, name: str) -> None:
        """Background task to read output from a standard subprocess.
        
        Args:
            name: Name of the process
        """
        try:
            if name not in self.processes or name not in self.active_processes:
                logger.error(f"Process '{name}' not found for reading")
                return
            
            proc_info = self.processes[name]
            active_info = self.active_processes[name]
            process = proc_info.get("process")
            buffer = active_info.get("buffer", bytearray())
            structured = proc_info.get("structured_output", False)
            buffer_size = proc_info.get("buffer_size", 10240)
            
            while name in self.active_processes:
                try:
                    # Read from stdout and stderr
                    stdout_chunk = await process.stdout.read(1024)
                    stderr_chunk = await process.stderr.read(1024)
                    
                    if not stdout_chunk and not stderr_chunk:
                        # Both streams have reached EOF
                        logger.debug(f"EOF reached for process '{name}'")
                        break
                    
                    # Combine the chunks
                    chunk = stdout_chunk + stderr_chunk
                    
                    # Append to buffer, respecting size limit
                    buffer.extend(chunk)
                    if len(buffer) > buffer_size:
                        # Trim buffer from the beginning
                        buffer = buffer[-buffer_size:]
                    
                    # Update buffer in active_info
                    active_info["buffer"] = buffer
                    
                    # Process structured output if enabled
                    if structured:
                        await self._process_structured_output(name, chunk)
                    
                    # Call output callback if registered
                    callback = active_info.get("output_callback")
                    if callback:
                        try:
                            await callback(chunk.decode("utf-8", errors="replace"))
                        except Exception as e:
                            logger.error(f"Error in output callback: {str(e)}")
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error reading from subprocess: {str(e)}")
                    await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in subprocess reader task: {str(e)}")
        finally:
            # Clean up if needed
            if name in self.active_processes:
                if not self.active_processes.get(name, {}).get("keep_open", False):
                    await self.exit_process(name)
    
    async def _process_structured_output(self, name: str, chunk: bytes) -> None:
        """Process output chunk looking for structured JSON data.
        
        Args:
            name: Name of the process
            chunk: Raw output chunk
        """
        try:
            text = chunk.decode("utf-8", errors="replace")
            
            # Look for JSON objects
            for line in text.splitlines():
                line = line.strip()
                if not line or not (line.startswith('{') and line.endswith('}')):
                    continue
                
                try:
                    data = json.loads(line)
                    # Store structured output in process info for later retrieval
                    proc_info = self.processes.get(name, {})
                    structured_data = proc_info.get("structured_data", [])
                    structured_data.append(data)
                    
                    # Keep only the latest entries
                    max_entries = 100
                    if len(structured_data) > max_entries:
                        structured_data = structured_data[-max_entries:]
                    
                    proc_info["structured_data"] = structured_data
                except json.JSONDecodeError:
                    # Not valid JSON, ignore
                    pass
        except Exception as e:
            logger.error(f"Error processing structured output: {str(e)}")
    
    async def send_command(self, name: str, command: str, add_newline: bool = True) -> bool:
        """Send a command to an interactive process.
        
        Args:
            name: Name of the process
            command: Command string to send
            add_newline: Whether to add a newline character
            
        Returns:
            True if successful, False otherwise
        """
        if name not in self.active_processes:
            logger.error(f"Not in interactive mode with process '{name}'")
            return False
        
        try:
            proc_info = self.processes.get(name, {})
            use_pty = proc_info.get("use_pty", False)
            
            if add_newline and not command.endswith('\n'):
                command += '\n'
            
            if use_pty:
                # PTY process - write to master fd
                master_fd = proc_info.get("master_fd")
                if master_fd is not None:
                    os.write(master_fd, command.encode('utf-8'))
                    return True
            else:
                # Standard subprocess - write to stdin
                process = proc_info.get("process")
                if process and process.stdin:
                    process.stdin.write(command.encode('utf-8'))
                    await process.stdin.drain()
                    return True
            
            logger.error(f"Failed to send command to process '{name}'")
            return False
        except Exception as e:
            logger.error(f"Error sending command to process '{name}': {str(e)}")
            return False
    
    async def get_output(self, name: str, clear: bool = False) -> str:
        """Get captured output from the process buffer.
        
        Args:
            name: Name of the process
            clear: Whether to clear the buffer after reading
            
        Returns:
            Captured output as string
        """
        if name not in self.active_processes:
            logger.error(f"Not in interactive mode with process '{name}'")
            return ""
        
        try:
            active_info = self.active_processes.get(name, {})
            buffer = active_info.get("buffer", bytearray())
            
            output = buffer.decode("utf-8", errors="replace")
            
            if clear:
                active_info["buffer"] = bytearray()
            
            return output
        except Exception as e:
            logger.error(f"Error getting output from process '{name}': {str(e)}")
            return ""
    
    async def get_structured_data(self, name: str, clear: bool = False) -> List[Dict[str, Any]]:
        """Get structured JSON data captured from the process.
        
        Args:
            name: Name of the process
            clear: Whether to clear the data after reading
            
        Returns:
            List of structured data objects
        """
        if name not in self.processes:
            logger.error(f"Process '{name}' not found")
            return []
        
        try:
            proc_info = self.processes.get(name, {})
            data = proc_info.get("structured_data", [])
            
            if clear:
                proc_info["structured_data"] = []
            
            return data
        except Exception as e:
            logger.error(f"Error getting structured data from process '{name}': {str(e)}")
            return []
    
    async def exit_process(self, name: str) -> bool:
        """Exit interactive mode with a process.
        
        Args:
            name: Name of the process
            
        Returns:
            True if successful, False otherwise
        """
        if name not in self.active_processes:
            logger.warning(f"Not in interactive mode with process '{name}'")
            return False
        
        try:
            # Remove from active processes
            del self.active_processes[name]
            logger.info(f"Exited interactive mode with process '{name}'")
            return True
        except Exception as e:
            logger.error(f"Error exiting process '{name}': {str(e)}")
            return False
    
    async def resize_terminal(self, name: str, rows: int, cols: int) -> bool:
        """Resize the terminal of a PTY process.
        
        Args:
            name: Name of the process
            rows: Number of rows
            cols: Number of columns
            
        Returns:
            True if successful, False otherwise
        """
        if name not in self.processes:
            logger.error(f"Process '{name}' not found")
            return False
        
        proc_info = self.processes.get(name, {})
        use_pty = proc_info.get("use_pty", False)
        
        if not use_pty:
            logger.warning(f"Process '{name}' is not using a PTY")
            return False
        
        try:
            master_fd = proc_info.get("master_fd")
            if master_fd is not None:
                # Create the terminal size struct
                term_size = struct.pack('HHHH', rows, cols, 0, 0)
                fcntl.ioctl(master_fd, termios.TIOCSWINSZ, term_size)
                
                # Send SIGWINCH to notify of the change
                pid = proc_info.get("pid")
                if pid:
                    try:
                        os.kill(pid, signal.SIGWINCH)
                    except ProcessLookupError:
                        # Process no longer exists
                        pass
                
                return True
            
            logger.error(f"Master FD not found for process '{name}'")
            return False
        except Exception as e:
            logger.error(f"Error resizing terminal for process '{name}': {str(e)}")
            return False
    
    def close(self):
        """Clean up resources used by the process manager."""
        try:
            # Cancel monitor task
            if self.monitor_task:
                self.monitor_task.cancel()
            
            # Stop all processes
            for name in list(self.processes.keys()):
                asyncio.ensure_future(self.stop_process(name, timeout=1.0))
        except Exception as e:
            logger.error(f"Error in process manager cleanup: {str(e)}") 