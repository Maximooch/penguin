from mcp import FastMCP # type: ignore

# Create an MCP server instance for the Echo service
echo_mcp = FastMCP("Echo")

@echo_mcp.resource("echo://{message}")
def echo_resource(message: str) -> str:
    """Echo a message as a resource.
    
    Args:
        message: The message to echo back
        
    Returns:
        The echoed message prefixed with 'Resource echo:'
    """
    return f"Resource echo: {message}"

@echo_mcp.tool()
def echo_tool(message: str) -> str:
    """Echo a message as a tool.
    
    Args:
        message: The message to echo back
        
    Returns:
        The echoed message prefixed with 'Tool echo:'
    """
    return f"Tool echo: {message}"

@echo_mcp.prompt()
def echo_prompt(message: str) -> str:
    """Create an echo prompt.
    
    Args:
        message: The message to include in the prompt
        
    Returns:
        A prompt string containing the provided message
    """
    return f"Please process this message: {message}"


def start_server(host: str = "localhost", port: int = 8000):
    """Start the Echo MCP server"""
    print(f"Starting Echo MCP server on {host}:{port}")
    echo_mcp.run(host=host, port=port)


if __name__ == "__main__":
    # This allows running the echo server directly
    print("Starting Echo MCP server...")
    start_server() 