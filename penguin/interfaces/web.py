from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any

class WebInterface:
    def __init__(self, cli):
        self.app = FastAPI()
        self.cli = cli
        
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        self.setup_routes()
    
    def format_response(self, response: Any) -> str:
        """Format the response similar to CLI display"""
        if isinstance(response, dict):
            formatted = ""
            
            # Add main response if present
            if 'assistant_response' in response:
                formatted += str(response['assistant_response'])
            
            # Add action results if present
            if 'action_results' in response and response['action_results']:
                formatted += "\n\nTool Results:\n"
                for result in response['action_results']:
                    action = result.get('action', 'unknown')
                    result_text = result.get('result', '')
                    formatted += f"• {action}: {result_text}\n"
            
            return formatted
        
        return str(response)
    
    def setup_routes(self):
        @self.app.post("/chat")
        async def chat(message: Dict[str, str]):
            # Use the core's methods directly since that's what CLI uses internally
            await self.cli.core.process_input({"text": message["text"]})
            response, _ = await self.cli.core.get_response()
            
            # Format the response
            formatted_response = self.format_response(response)
            return {"response": formatted_response}
        
        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            while True:
                try:
                    message = await websocket.receive_json()
                    # Use core's methods directly
                    await self.cli.core.process_input({"text": message["text"]})
                    response, _ = await self.cli.core.get_response()
                    
                    # Format the response
                    formatted_response = self.format_response(response)
                    await websocket.send_json({"response": formatted_response})
                except Exception as e:
                    print(f"Error processing message: {e}")
                    await websocket.send_json({"error": str(e)}) 