import asyncio
import json
from typing import Set

import websockets
from new_core import PenguinCore


class PenguinWebSocketServer:
    def __init__(self, core: PenguinCore):
        self.core = core
        self.clients: Set[websockets.WebSocketServerProtocol] = set()

    async def register(self, websocket: websockets.WebSocketServerProtocol):
        self.clients.add(websocket)

    async def unregister(self, websocket: websockets.WebSocketServerProtocol):
        self.clients.remove(websocket)

    async def broadcast_task_update(self, tasks: list):
        if self.clients:
            message = json.dumps({"type": "task_update", "tasks": tasks})
            await asyncio.gather(*[client.send(message) for client in self.clients])

    async def handle_message(
        self, websocket: websockets.WebSocketServerProtocol, message: str
    ):
        try:
            data = json.loads(message)
            if data["type"] == "message":
                # Process the message through PenguinCore
                response = await self.core.process_message(data["content"])

                # Send response back to client
                await websocket.send(
                    json.dumps({"type": "message", "content": response})
                )

                # If the message generated any tasks, broadcast them
                tasks = await self.core.get_current_tasks()
                if tasks:
                    await self.broadcast_task_update(tasks)

        except json.JSONDecodeError:
            await websocket.send(
                json.dumps({"type": "error", "content": "Invalid message format"})
            )

    async def handle_client(self, websocket: websockets.WebSocketServerProtocol):
        await self.register(websocket)
        try:
            async for message in websocket:
                await self.handle_message(websocket, message)
        finally:
            await self.unregister(websocket)

    async def start(self, host: str = "localhost", port: int = 8000):
        async with websockets.serve(self.handle_client, host, port):
            print(f"WebSocket server started on ws://{host}:{port}")
            await asyncio.Future()  # run forever

    def run(self, host: str = "localhost", port: int = 8000):
        asyncio.run(self.start(host, port))
