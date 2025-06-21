"""Container execution support for sandboxed agent runs.

This provides Docker-based isolation for agent execution, implementing the
sandbox functionality outlined in the Agent consolidation plan.
"""
from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

class ContainerExecutor:
    """Handles containerized agent execution for security and isolation."""
    
    def __init__(self, image_name: str = "penguin-agent:latest", workspace_mount: Optional[str] = None):
        self.image_name = image_name
        self.workspace_mount = workspace_mount or "/tmp/penguin_workspace"
        self.containers = {}  # Track running containers
        
    async def execute_agent(
        self, 
        agent_config: Dict[str, Any], 
        prompt: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute an agent in a container with I/O over stdin/stdout JSON RPC."""
        
        try:
            # Check if Docker is available
            if not await self._check_docker_available():
                logger.warning("Docker not available, falling back to in-process execution")
                return await self._fallback_execution(agent_config, prompt, context)
            
            # Create container with mounted workspace
            container_id = await self._create_container(agent_config)
            
            # Send RPC request and get response
            request_data = {
                "method": "run_agent",
                "params": {
                    "prompt": prompt,
                    "context": context or {},
                    "config": agent_config
                }
            }
            
            result = await self._send_rpc_request(container_id, request_data)
            
            # Cleanup container
            await self._cleanup_container(container_id)
            
            return result
            
        except Exception as e:
            logger.exception(f"Container execution failed: {e}")
            return {
                "status": "error",
                "error": f"Container execution failed: {str(e)}",
                "fallback_used": True
            }
    
    async def _check_docker_available(self) -> bool:
        """Check if Docker is available and accessible."""
        try:
            # Try to run simple docker command
            process = await asyncio.create_subprocess_exec(
                'docker', 'version',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            return process.returncode == 0
        except (FileNotFoundError, OSError):
            return False
    
    async def _create_container(self, agent_config: Dict[str, Any]) -> str:
        """Create and start a Docker container for agent execution."""
        
        # Generate unique container name
        import uuid
        container_name = f"penguin-agent-{uuid.uuid4().hex[:8]}"
        
        # Prepare Docker command
        docker_cmd = [
            'docker', 'run', '--rm', '-d',
            '--name', container_name,
            '-v', f'{self.workspace_mount}:/workspace:ro',  # Read-only workspace mount
            '-v', '/tmp:/tmp:rw',  # Writable temp directory
            '--memory', '512m',  # Memory limit
            '--cpus', '1.0',  # CPU limit
            '--network', 'none',  # No network access by default
            self.image_name,
            'python', '-m', 'penguin.agent.container_runner'  # Entry point
        ]
        
        # Create container
        process = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise RuntimeError(f"Failed to create container: {stderr.decode()}")
        
        container_id = stdout.decode().strip()
        self.containers[container_id] = container_name
        
        # Wait for container to be ready
        await asyncio.sleep(1)
        
        return container_id
    
    async def _send_rpc_request(self, container_id: str, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send JSON-RPC request to container and get response."""
        
        # Prepare input
        input_json = json.dumps(request_data) + '\n'
        
        # Execute command in container
        process = await asyncio.create_subprocess_exec(
            'docker', 'exec', '-i', container_id, 'python', '-m', 'penguin.agent.container_runner',
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Send request and get response
        stdout, stderr = await process.communicate(input_json.encode())
        
        if process.returncode != 0:
            raise RuntimeError(f"Container execution failed: {stderr.decode()}")
        
        # Parse JSON response
        try:
            response = json.loads(stdout.decode())
            return response
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON response from container: {e}")
    
    async def _cleanup_container(self, container_id: str) -> None:
        """Stop and remove container."""
        try:
            # Stop container
            await asyncio.create_subprocess_exec(
                'docker', 'stop', container_id,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            
            # Remove from tracking
            self.containers.pop(container_id, None)
            
        except Exception as e:
            logger.warning(f"Failed to cleanup container {container_id}: {e}")
    
    async def _fallback_execution(
        self, 
        agent_config: Dict[str, Any], 
        prompt: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Fallback to in-process execution when Docker is not available."""
        
        # Import here to avoid circular dependencies
        from penguin.agent.basic_agent import BasicPenguinAgent
        from penguin.agent.schema import AgentConfig, SecurityConfig
        
        # Create a mock agent configuration  
        mock_config = AgentConfig(
            name=agent_config.get("name", "fallback_agent"),
            type="penguin.agent.basic_agent.BasicPenguinAgent",
            description="Fallback agent execution",
            security=SecurityConfig()
        )
        
        # Mock required components (in real usage these would come from Core)
        from unittest.mock import AsyncMock
        mock_components = {
            'conversation_manager': AsyncMock(),
            'api_client': AsyncMock(),
            'tool_manager': AsyncMock(),
            'action_executor': AsyncMock()
        }
        
        # Configure mock conversation manager to return a response
        mock_components['conversation_manager'].process_message = AsyncMock(return_value={
            "assistant_response": f"Fallback response to: {prompt}",
            "action_results": []
        })
        
        # Create and run agent
        agent = BasicPenguinAgent(mock_config, **mock_components)
        
        result = await agent.run(prompt, context)
        result["fallback_used"] = True
        
        return result 