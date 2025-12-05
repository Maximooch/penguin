"""Temporal client wrapper with connection management.

Provides a high-level interface to the Temporal Python SDK with:
- Connection management and retry logic
- Local dev mode (auto-start Temporal server)
- Health checking
"""

import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Check if temporalio is available
try:
    from temporalio.client import Client
    from temporalio.service import ServiceClient
    TEMPORAL_AVAILABLE = True
except ImportError:
    TEMPORAL_AVAILABLE = False
    Client = None
    ServiceClient = None


class TemporalClient:
    """Wrapper around Temporal client with connection management."""
    
    def __init__(
        self,
        address: str = "localhost:7233",
        namespace: str = "penguin",
        auto_start: bool = True,
    ):
        """Initialize Temporal client.
        
        Args:
            address: Temporal server address.
            namespace: Temporal namespace.
            auto_start: Whether to auto-start local Temporal server.
        """
        if not TEMPORAL_AVAILABLE:
            raise ImportError(
                "temporalio package not installed. "
                "Install with: pip install temporalio"
            )
        
        self.address = address
        self.namespace = namespace
        self.auto_start = auto_start
        
        self._client: Optional[Client] = None
        self._local_server_process: Optional[subprocess.Popen] = None
        self._connected = False
    
    async def connect(self) -> Client:
        """Connect to Temporal server.
        
        Returns:
            Connected Temporal client.
        """
        if self._client and self._connected:
            return self._client
        
        # Try to connect
        try:
            self._client = await Client.connect(
                self.address,
                namespace=self.namespace,
            )
            self._connected = True
            logger.info(f"Connected to Temporal at {self.address}")
            return self._client
        
        except Exception as e:
            logger.warning(f"Could not connect to Temporal: {e}")
            
            # Try auto-starting local server
            if self.auto_start and "localhost" in self.address:
                logger.info("Attempting to start local Temporal server...")
                if await self._start_local_server():
                    # Retry connection
                    await asyncio.sleep(2)  # Wait for server to start
                    self._client = await Client.connect(
                        self.address,
                        namespace=self.namespace,
                    )
                    self._connected = True
                    logger.info("Connected to local Temporal server")
                    return self._client
            
            raise
    
    async def _start_local_server(self) -> bool:
        """Start local Temporal server using temporal CLI.
        
        Returns:
            True if server started successfully.
        """
        try:
            # Check if temporal CLI is available
            result = subprocess.run(
                ["temporal", "--version"],
                capture_output=True,
                text=True,
            )
            
            if result.returncode != 0:
                logger.error("Temporal CLI not found. Install with: brew install temporal")
                return False
            
            # Start server in dev mode
            self._local_server_process = subprocess.Popen(
                ["temporal", "server", "start-dev", "--namespace", self.namespace],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            
            logger.info("Started local Temporal server in dev mode")
            return True
        
        except FileNotFoundError:
            logger.error("Temporal CLI not found. Install with: brew install temporal")
            return False
        except Exception as e:
            logger.error(f"Failed to start local Temporal server: {e}")
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from Temporal server."""
        self._connected = False
        self._client = None
        
        # Stop local server if we started it
        if self._local_server_process:
            self._local_server_process.terminate()
            self._local_server_process = None
            logger.info("Stopped local Temporal server")
    
    async def is_healthy(self) -> bool:
        """Check if Temporal connection is healthy.
        
        Returns:
            True if connected and healthy.
        """
        if not self._client or not self._connected:
            return False
        
        try:
            # Try a simple operation to verify connection
            await self._client.service_client.check_health()
            return True
        except Exception:
            return False
    
    @property
    def client(self) -> Optional[Client]:
        """Get the underlying Temporal client."""
        return self._client
    
    @property
    def connected(self) -> bool:
        """Check if connected."""
        return self._connected


# Singleton instance
_temporal_client: Optional[TemporalClient] = None


async def get_temporal_client(
    address: str = "localhost:7233",
    namespace: str = "penguin",
    auto_start: bool = True,
) -> TemporalClient:
    """Get or create Temporal client singleton.
    
    Args:
        address: Temporal server address.
        namespace: Temporal namespace.
        auto_start: Whether to auto-start local server.
        
    Returns:
        Connected TemporalClient instance.
    """
    global _temporal_client
    
    if _temporal_client is None:
        _temporal_client = TemporalClient(address, namespace, auto_start)
    
    await _temporal_client.connect()
    return _temporal_client

