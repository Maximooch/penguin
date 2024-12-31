import asyncio
import uvicorn # type: ignore
from main import init_components
from interfaces.web import WebInterface

async def setup():
    # Initialize Penguin core through init_components
    cli = await init_components()
    return cli

def main():
    # Get the CLI instance using asyncio
    cli = asyncio.run(setup())
    
    # Pass the CLI instance to WebInterface
    interface = WebInterface(cli)
    
    # Run the server
    uvicorn.run(interface.app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main() 