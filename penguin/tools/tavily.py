import os
from tavily import TavilyClient
from typing import Dict, Any

class TavilySearch:
    def __init__(self):
        self.api_key = os.environ.get("TAVILY_API_KEY")
        if not self.api_key:
            raise ValueError("TAVILY_API_KEY environment variable is not set")
        self.client = TavilyClient(api_key=self.api_key)

    def search(self, query: str, max_results: int = 5, search_depth: str = "advanced") -> Dict[str, Any]:
        try:
            response = self.client.search(query=query, max_results=max_results, search_depth=search_depth)
            return response
        except Exception as e:
            return {"error": f"Error performing Tavily search: {str(e)}"}