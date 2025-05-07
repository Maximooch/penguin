"""Chrome DevTools Protocol debugger for Penguin.

This module provides direct access to Chrome's debugging capabilities
through the Chrome DevTools Protocol (CDP) via WebSockets.
"""

import asyncio
import json
import logging
import os
import base64
from typing import Dict, List, Any, Optional, Callable, Union
import websockets
import aiohttp
from datetime import datetime

logger = logging.getLogger(__name__)

class ChromeDebuggerError(Exception):
    """Base exception for Chrome debugger errors."""
    pass

class ChromeDebugger:
    """Chrome DevTools Protocol debugger interface.
    
    Provides direct access to Chrome's debugging capabilities through CDP.
    """
    
    def __init__(self, host: str = "localhost", port: int = 9222):
        """Initialize the Chrome debugger.
        
        Args:
            host: The host where Chrome is running with remote debugging enabled
            port: The remote debugging port
        """
        self.host = host
        self.port = port
        self.ws_url = None
        self.ws = None
        self.connected = False
        self.message_id = 0
        self.pending_messages = {}
        self.event_handlers = {}
        self.domains_enabled = set()
        self.target_id = None
        self.screenshots_dir = os.path.join(os.getcwd(), "screenshots")
        os.makedirs(self.screenshots_dir, exist_ok=True)
        
        # Task for background message processing
        self._message_task = None
    
    async def connect(self, target_type: str = "page") -> bool:
        """Connect to a Chrome debugging target.
        
        Args:
            target_type: Type of target to connect to ("page", "browser", etc.)
            
        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Get available targets
            targets = await self._get_targets()
            
            # Find a suitable target
            for target in targets:
                if target.get("type") == target_type:
                    self.target_id = target.get("id")
                    self.ws_url = target.get("webSocketDebuggerUrl")
                    break
            
            if not self.ws_url:
                raise ChromeDebuggerError(f"No {target_type} targets found")
            
            # Connect WebSocket
            self.ws = await websockets.connect(
                self.ws_url,
                max_size=None,  # No message size limit
                ping_interval=None,  # Disable ping to avoid interference
            )
            
            # Start message processing task
            self._message_task = asyncio.create_task(self._process_messages())
            
            self.connected = True
            logger.info(f"Connected to Chrome debugger at {self.ws_url}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Chrome debugger: {str(e)}")
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from the Chrome debugger."""
        if self._message_task:
            self._message_task.cancel()
            try:
                await self._message_task
            except asyncio.CancelledError:
                pass
        
        if self.ws:
            await self.ws.close()
            self.ws = None
            
        self.connected = False
        logger.info("Disconnected from Chrome debugger")
    
    async def enable_domain(self, domain: str) -> bool:
        """Enable a CDP domain.
        
        Args:
            domain: The domain to enable (e.g., "Page", "Network")
            
        Returns:
            True if successful, False otherwise
        """
        try:
            result = await self.execute(f"{domain}.enable")
            if result:
                self.domains_enabled.add(domain)
                logger.debug(f"Enabled {domain} domain")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to enable {domain} domain: {str(e)}")
            return False
    
    async def execute(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute a CDP method.
        
        Args:
            method: The method to execute (e.g., "Page.navigate")
            params: Parameters for the method
            
        Returns:
            The result from the method execution
        """
        if not self.connected or not self.ws:
            raise ChromeDebuggerError("Not connected to Chrome debugger")
        
        message_id = self.message_id
        self.message_id += 1
        
        message = {
            "id": message_id,
            "method": method,
        }
        
        if params:
            message["params"] = params
        
        # Create a future for this message
        future = asyncio.Future()
        self.pending_messages[message_id] = future
        
        # Send the message
        await self.ws.send(json.dumps(message))
        
        # Wait for the response
        try:
            result = await asyncio.wait_for(future, timeout=30)
            return result
        except asyncio.TimeoutError:
            del self.pending_messages[message_id]
            raise ChromeDebuggerError(f"Timeout waiting for response to {method}")
    
    async def register_event_handler(self, event: str, handler: Callable) -> None:
        """Register a handler for CDP events.
        
        Args:
            event: The event to handle (e.g., "Page.loadEventFired")
            handler: Callback function to handle the event
        """
        self.event_handlers[event] = handler
        logger.debug(f"Registered handler for {event}")
    
    async def navigate(self, url: str) -> bool:
        """Navigate to a URL.
        
        Args:
            url: The URL to navigate to
            
        Returns:
            True if navigation started successfully
        """
        try:
            if "Page" not in self.domains_enabled:
                await self.enable_domain("Page")
                
            result = await self.execute("Page.navigate", {"url": url})
            return "frameId" in result
        except Exception as e:
            logger.error(f"Navigation error: {str(e)}")
            return False
    
    async def take_screenshot(self, filepath: str = None, full_page: bool = False) -> str:
        """Take a screenshot of the current page.
        
        Args:
            filepath: Path to save the screenshot, or None to use auto-generated name
            full_page: Whether to capture the full page or just the viewport
            
        Returns:
            Path to the saved screenshot
        """
        try:
            if "Page" not in self.domains_enabled:
                await self.enable_domain("Page")
            
            # Set clip for full page if needed
            params = {}
            if full_page:
                # Get page metrics first
                layout_metrics = await self.execute("Page.getLayoutMetrics")
                content_size = layout_metrics.get("contentSize", {})
                params = {
                    "clip": {
                        "x": 0,
                        "y": 0,
                        "width": content_size.get("width", 800),
                        "height": content_size.get("height", 600),
                        "scale": 1
                    }
                }
            
            # Capture screenshot
            result = await self.execute("Page.captureScreenshot", params)
            if not result or "data" not in result:
                raise ChromeDebuggerError("Failed to capture screenshot")
            
            # Decode base64 data
            img_data = base64.b64decode(result["data"])
            
            # Save to file
            if not filepath:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filepath = os.path.join(self.screenshots_dir, f"screenshot_{timestamp}.png")
            
            with open(filepath, "wb") as f:
                f.write(img_data)
            
            logger.info(f"Screenshot saved to {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"Screenshot error: {str(e)}")
            raise ChromeDebuggerError(f"Failed to take screenshot: {str(e)}")
    
    async def get_console_logs(self) -> List[Dict[str, Any]]:
        """Get console logs from the browser.
        
        Returns:
            List of console log entries
        """
        try:
            if "Console" not in self.domains_enabled:
                await self.enable_domain("Console")
                
            # The Console domain doesn't have a method to get past logs,
            # so we can only return logs that come in after enabling
            return []
        except Exception as e:
            logger.error(f"Error getting console logs: {str(e)}")
            return []

    async def evaluate_javascript(self, expression: str) -> Any:
        """Evaluate JavaScript in the browser.
        
        Args:
            expression: JavaScript expression to evaluate
            
        Returns:
            Result of the evaluation
        """
        try:
            if "Runtime" not in self.domains_enabled:
                await self.enable_domain("Runtime")
                
            result = await self.execute("Runtime.evaluate", {
                "expression": expression,
                "returnByValue": True
            })
            
            if "result" in result:
                return result["result"].get("value")
            elif "exceptionDetails" in result:
                error_msg = result["exceptionDetails"].get("text", "Unknown error")
                raise ChromeDebuggerError(f"JavaScript evaluation error: {error_msg}")
            
            return None
        except Exception as e:
            logger.error(f"JavaScript evaluation error: {str(e)}")
            raise ChromeDebuggerError(f"Failed to evaluate JavaScript: {str(e)}")
    
    # Internal methods
    
    async def _get_targets(self) -> List[Dict[str, Any]]:
        """Get available debugging targets from Chrome.
        
        Returns:
            List of targets
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{self.host}:{self.port}/json/list") as response:
                    if response.status != 200:
                        raise ChromeDebuggerError(f"Failed to get targets: HTTP {response.status}")
                    return await response.json()
        except Exception as e:
            logger.error(f"Error getting targets: {str(e)}")
            raise ChromeDebuggerError(f"Failed to get targets: {str(e)}")
    
    async def _process_messages(self) -> None:
        """Background task to process incoming messages from Chrome."""
        try:
            while True:
                if not self.ws:
                    break
                    
                message = await self.ws.recv()
                data = json.loads(message)
                
                # Handle method response
                if "id" in data:
                    message_id = data["id"]
                    if message_id in self.pending_messages:
                        future = self.pending_messages.pop(message_id)
                        if "result" in data:
                            future.set_result(data["result"])
                        elif "error" in data:
                            future.set_exception(ChromeDebuggerError(
                                f"CDP error: {data['error'].get('message', 'Unknown error')}"
                            ))
                
                # Handle event
                elif "method" in data:
                    event = data["method"]
                    params = data.get("params", {})
                    
                    # Log console messages immediately
                    if event == "Console.messageAdded":
                        message = params.get("message", {})
                        text = message.get("text", "")
                        logger.info(f"Console: {text}")
                    
                    # Call registered handler
                    if event in self.event_handlers:
                        try:
                            handler = self.event_handlers[event]
                            await handler(params)
                        except Exception as e:
                            logger.error(f"Error in event handler for {event}: {str(e)}")
        
        except asyncio.CancelledError:
            # Task was cancelled, exit gracefully
            pass
        except Exception as e:
            logger.error(f"Error processing messages: {str(e)}") 