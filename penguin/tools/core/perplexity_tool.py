import logging
from typing import Dict, List

import requests

from penguin.config import PERPLEXITY_API_KEY

from .web_search import WebSearchProvider

logger = logging.getLogger(__name__)


class PerplexityProvider(WebSearchProvider):
    def __init__(self):
        self.api_key = PERPLEXITY_API_KEY
        if not self.api_key:
            raise ValueError("PERPLEXITY_API_KEY environment variable is not set")
        self.base_url = "https://api.perplexity.ai/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        try:
            payload = {
                "model": "sonar",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are an artificial intelligence assistant. Provide a concise summary of the latest AI news in bullet points.",
                    },
                    {"role": "user", "content": query},
                ],
            }

            response = requests.post(self.base_url, headers=self.headers, json=payload)
            response.raise_for_status()

            data = response.json()
            content = data["choices"][0]["message"]["content"]

            # Convert the content into our expected format
            return [{"title": "Latest AI News", "snippet": content}]

        except requests.exceptions.RequestException as e:
            logger.error(f"Error occurred: {str(e)}")
            return []

    def format_results(self, results: List[Dict[str, str]]) -> str:
        formatted = []
        for result in results:
            formatted.append(f"Title: {result['title']}")
            formatted.append(f"Snippet: {result['snippet']}")
            formatted.append("---")
        return "\n".join(formatted)
