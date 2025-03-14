import subprocess
from typing import Dict, Optional, Tuple, Any
import asyncio
import logging

logger = logging.getLogger(__name__)

class ProcessManager:
    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}
        self.active_processes: Dict[str, Tuple[asyncio.StreamReader, asyncio.StreamWriter]] = {}

    async def start_process(self, name: str, command: str) -> str:
        try:
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=0,  # No buffering for interactive processes
            )
            self.processes[name] = process
            return f"Process '{name}' started with PID {process.pid}"
        except Exception as e:
            return f"Error starting process '{name}': {str(e)}"

    async def stop_process(self, name: str) -> str:
        if name in self.processes:
            process = self.processes[name]
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            del self.processes[name]
            
            # Clean up active process if needed
            if name in self.active_processes:
                reader, writer = self.active_processes[name]
                writer.close()
                await writer.wait_closed()
                del self.active_processes[name]
                
            return f"Process '{name}' stopped"
        return f"Process '{name}' not found"

    async def get_process_status(self, name: str) -> str:
        if name in self.processes:
            process = self.processes[name]
            if process.poll() is None:
                return f"Process '{name}' is running"
            else:
                return (
                    f"Process '{name}' has exited with return code {process.returncode}"
                )
        return f"Process '{name}' not found"

    async def list_processes(self) -> Dict[str, str]:
        return {
            name: "Running" if process.poll() is None else "Exited"
            for name, process in self.processes.items()
        }
        
    async def enter_process(self, name: str) -> Optional[asyncio.StreamReader]:
        """Connect to a process for interactive communication.
        
        Args:
            name: Name of the process to enter
            
        Returns:
            StreamReader if successful, None if process not found
        """
        if name not in self.processes:
            logger.error(f"Process '{name}' not found")
            return None
            
        process = self.processes[name]
        if process.poll() is not None:
            logger.error(f"Process '{name}' is not running")
            return None
            
        # Create stream reader and writer for process
        try:
            # Get file descriptors from process
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            
            # Use low-level transport-protocol API
            loop = asyncio.get_event_loop()
            transport, _ = await loop.connect_read_pipe(
                lambda: protocol, process.stdout
            )
            
            # Create a writer connected to stdin
            write_transport, _ = await loop.connect_write_pipe(
                asyncio.Protocol, process.stdin
            )
            writer = asyncio.StreamWriter(write_transport, protocol, reader, loop)
            
            # Store the streams
            self.active_processes[name] = (reader, writer)
            logger.debug(f"Successfully entered process '{name}'")
            return reader
        except Exception as e:
            logger.error(f"Error entering process '{name}': {str(e)}")
            return None
        
    async def send_command(self, name: str, command: str) -> str:
        """Send a command to an active process.
        
        Args:
            name: Name of the process
            command: Command to send
            
        Returns:
            Output from the command or error message
        """
        if name not in self.active_processes:
            return f"Not connected to process '{name}'"
            
        try:
            reader, writer = self.active_processes[name]
            
            # Send command with newline to simulate Enter key
            writer.write(f"{command}\n".encode())
            await writer.drain()
            
            # Read response (with timeout)
            try:
                response = await asyncio.wait_for(reader.read(1024), timeout=5.0)
                return response.decode()
            except asyncio.TimeoutError:
                return "Command sent, but no response received (timeout)"
                
        except Exception as e:
            logger.error(f"Error sending command to process '{name}': {str(e)}")
            return f"Error sending command: {str(e)}"
            
    async def exit_process(self, name: str) -> str:
        """Exit an interactive process session.
        
        Args:
            name: Name of the process
            
        Returns:
            Success or error message
        """
        if name not in self.active_processes:
            return f"Not connected to process '{name}'"
            
        try:
            reader, writer = self.active_processes[name]
            writer.close()
            await writer.wait_closed()
            del self.active_processes[name]
            return f"Exited process '{name}'"
        except Exception as e:
            logger.error(f"Error exiting process '{name}': {str(e)}")
            return f"Error exiting process: {str(e)}"
