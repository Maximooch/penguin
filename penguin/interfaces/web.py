import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware


class WebInterface:
    def __init__(self, cli):
        self.app = FastAPI()
        self.cli = cli
        self.active_connections: Dict[str, WebSocket] = {}

        # Setup CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Initialize workspace paths
        self.workspace_path = Path("workspace")
        self.conversations_path = self.workspace_path / "conversations"
        self.conversations_path.mkdir(parents=True, exist_ok=True)

        # Setup routes
        self.setup_routes()

    def setup_routes(self):
        @self.app.get("/api/conversations")
        async def list_conversations():
            try:
                conversations = []
                for file in self.conversations_path.glob("*.json"):
                    try:
                        with open(file) as f:
                            data = json.load(f)
                            conversations.append(
                                {
                                    "metadata": {
                                        "session_id": file.stem,
                                        "title": data.get("title", "Untitled"),
                                        "last_active": data.get(
                                            "last_active", datetime.now().isoformat()
                                        ),
                                        "message_count": len(data.get("messages", [])),
                                    },
                                    "messages": data.get("messages", []),
                                }
                            )
                    except Exception as e:
                        print(f"Error reading conversation {file}: {e}")
                        continue

                # Sort by last_active descending
                conversations.sort(
                    key=lambda x: x["metadata"]["last_active"], reverse=True
                )
                return conversations

            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/api/conversations/new")
        async def create_conversation():
            try:
                # Generate new session ID
                session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

                # Create new conversation file
                conversation_data = {
                    "title": "New Conversation",
                    "last_active": datetime.now().isoformat(),
                    "messages": [],
                }

                conversation_file = self.conversations_path / f"{session_id}.json"
                with open(conversation_file, "w") as f:
                    json.dump(conversation_data, f, indent=2)

                return {
                    "session_id": session_id,
                    "metadata": {
                        "title": conversation_data["title"],
                        "last_active": conversation_data["last_active"],
                        "message_count": 0,
                    },
                }

            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.websocket("/ws/{session_id}")
        async def websocket_endpoint(websocket: WebSocket, session_id: str):
            await self.handle_websocket(websocket, session_id)

    async def handle_websocket(self, websocket: WebSocket, session_id: str):
        """Handle WebSocket connection for a chat session."""
        try:
            # Load existing messages from conversation file
            conversation_file = os.path.join(
                self.cli.core.workspace_path, "conversations", f"{session_id}.json"
            )
            if os.path.exists(conversation_file):
                with open(conversation_file) as f:
                    data = json.load(f)
                    # Add existing messages to conversation system
                    for msg in data.get("messages", []):
                        self.cli.core.conversation_system.add_message(
                            role=msg["role"], content=msg["content"]
                        )

            await websocket.accept()

            while True:
                try:
                    data = await websocket.receive_json()
                    user_message = data.get("text", "").strip()

                    if not user_message:
                        continue

                    # Add user message to conversation system
                    self.cli.core.conversation_system.add_message(
                        role="user", content=[{"text": user_message}]
                    )

                    # Get response from assistant
                    response = await self.cli.core.get_response(user_message)

                    # Add assistant response to conversation system
                    self.cli.core.conversation_system.add_message(
                        role="assistant", content=[{"text": response}]
                    )

                    # Send response back to client
                    await websocket.send_json({"response": response})

                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error handling message: {str(e)}")
                    await websocket.send_json(
                        {"error": f"Error processing message: {str(e)}"}
                    )

        except Exception as e:
            logger.error(f"WebSocket error: {str(e)}")
            if not websocket.client_state == WebSocketState.DISCONNECTED:
                await websocket.close()
