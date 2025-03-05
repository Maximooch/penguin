import argparse
from penguin.penguin.integrations.mcp.echo import start_server

def main():
    parser = argparse.ArgumentParser(description='Run the Echo MCP server')
    parser.add_argument('--host', default='localhost', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8000, help='Port to run on')
    
    args = parser.parse_args()
    
    print(f"Starting Echo MCP server on {args.host}:{args.port}")
    start_server(host=args.host, port=args.port)

if __name__ == "__main__":
    main() 