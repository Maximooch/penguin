from mcp import FastMCP # type: ignore
import argparse

# Create an MCP server instance for the Echo service
echo_mcp = FastMCP("Echo")

@echo_mcp.resource("echo://{message}")
def echo_resource(message: str) -> str:
    """Echo a message as a resource.
    
    Args:
        message: The message to echo
        
    Returns:
        The same message
    """
    return f"Echo resource: {message}"

@echo_mcp.tool()
def echo_tool(message: str) -> str:
    """Echo a message.
    
    Args:
        message: The message to echo
        
    Returns:
        The same message
    """
    return f"Echo tool: {message}"

@echo_mcp.prompt()
def echo_prompt(message: str) -> str:
    """Echo a message in the form of a prompt.
    
    Args:
        message: The message to echo
        
    Returns:
        A prompt containing the message
    """
    return f"Here is the message you asked for: {message}"

def start_server(host: str = "localhost", port: int = 8000):
    """Start the Echo MCP server"""
    print(f"Starting Echo MCP server on {host}:{port}")
    echo_mcp.run(host=host, port=port)

def main():
    parser = argparse.ArgumentParser(description='Run the Echo MCP server')
    parser.add_argument('--host', default='localhost', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8000, help='Port to run on')
    
    args = parser.parse_args()
    
    start_server(host=args.host, port=args.port)

if __name__ == "__main__":
    main() 