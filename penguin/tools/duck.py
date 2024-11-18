from duckduckgo_search import DDGS # type: ignore
import requests # type: ignore
from bs4 import BeautifulSoup # type: ignore
from typing import List, Dict
import re
from urllib.parse import urlparse

def clean_content(html: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()
    
    # Extract text
    text = soup.get_text()
    
    # Remove extra whitespace and newlines
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Remove common navigation and boilerplate text
    text = re.sub(r'(Skip to (main )?content|Open Navigation Menu|Menu|Search|Sign In|Subscribe|Newsletter)', '', text, flags=re.IGNORECASE)
    
    # Remove URLs
    text = re.sub(r'https?://\S+', '', text)
    
    # Truncate to 300 characters
    text = text[:300] + ('...' if len(text) > 300 else '')
    
    return text

def duckduckgo_search(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        
        formatted_results = []
        for i, result in enumerate(results, 1):
            try:
                if 'href' not in result:
                    raise KeyError("'href' not found in search result")
                
                title = result.get('title', 'No title available')
                snippet = result.get('body', 'No snippet available')
                
                # Clean up the snippet
                snippet = re.sub(r'\s+', ' ', snippet).strip()
                snippet = snippet[:200] + ('...' if len(snippet) > 200 else '')
                
                # Don't fetch content from the webpage to avoid potential issues
                formatted_result = {
                    "title": title,
                    "snippet": snippet,
                    "source": result['href']
                }
                formatted_results.append(formatted_result)
            except Exception as e:
                error_message = f"Error processing result {i}: {str(e)}"
                print(error_message)
                formatted_results.append({"error": error_message})
        
        if not formatted_results:
            return [{"error": "No results found or all results failed to process."}]
        
        return formatted_results
    
    except Exception as e:
        error_message = f"Error performing DuckDuckGo search: {str(e)}"
        print(error_message)
        return [{"error": error_message}]

# if __name__ == "__main__":
#     query = {"latest fighting news"}
#     max_results = 5
#     print(f"Searching for: '{query}' (max results: {max_results})")
#     duckduckgo_search(query, max_results)