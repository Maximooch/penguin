import os
import json
from typing import List, Dict, Any
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from sentence_transformers import SentenceTransformer

class MemorySearch:
    """
    A class for searching and managing log entries using both keyword and semantic search methods.
    """

    def __init__(self, log_dir: str = 'logs'):
        """
        Initialize the MemorySearch object.

        :param log_dir: Directory where log files are stored
        """
        self.log_dir = log_dir
        self.logs = self.load_logs()
        
        if not self.logs:
            print("No logs found. MemorySearch initialized with empty data.")
            self.tfidf_vectorizer = TfidfVectorizer()
            self.tfidf_matrix = None
            self.model = SentenceTransformer('paraphrase-MiniLM-L3-v2')
            self.embeddings = None
        else:
            self.tfidf_vectorizer = TfidfVectorizer()
            self.tfidf_matrix = self.tfidf_vectorizer.fit_transform([log['content'] for log in self.logs])
            self.model = SentenceTransformer('paraphrase-MiniLM-L3-v2')
            self.embeddings = self.compute_embeddings()

    def load_logs(self) -> List[Dict[str, Any]]:
        """
        Load all JSON log files from the log directory.

        :return: List of log entries
        """
        logs = []
        try:
            for filename in os.listdir(self.log_dir):
                if filename.endswith('.json'):
                    with open(os.path.join(self.log_dir, filename), 'r') as f:
                        logs.extend(json.load(f))
        except FileNotFoundError:
            print(f"Log directory '{self.log_dir}' not found.")
        except Exception as e:
            print(f"Error loading logs: {e}")
        return logs

    def compute_embeddings(self) -> np.ndarray:
        """
        Compute embeddings for all log entries using the sentence transformer model.

        :return: numpy array of embeddings
        """
        if not self.logs:
            return np.array([])
        return self.model.encode([log['content'] for log in self.logs])

    def keyword_search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Perform keyword-based search using TF-IDF and cosine similarity.

        :param query: Search query
        :param k: Number of top results to return
        :return: List of top k matching log entries
        """
        if self.tfidf_matrix is None:
            print("No logs available for keyword search.")
            return []
        
        query_vec = self.tfidf_vectorizer.transform([query])
        similarities = cosine_similarity(query_vec, self.tfidf_matrix)[0]
        top_k_indices = similarities.argsort()[-k:][::-1]
        return [self.logs[i] for i in top_k_indices]

    def semantic_search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Perform semantic search using sentence embeddings and cosine similarity.

        :param query: Search query
        :param k: Number of top results to return
        :return: List of top k matching log entries
        """
        if self.embeddings is None:
            print("No logs available for semantic search.")
            return []
        
        query_embedding = self.model.encode([query])
        similarities = cosine_similarity(query_embedding, self.embeddings)[0]
        top_k_indices = similarities.argsort()[-k:][::-1]
        return [self.logs[i] for i in top_k_indices]

    def combined_search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Perform both keyword and semantic search, combine results, and return top k unique entries.

        :param query: Search query
        :param k: Number of top results to return
        :return: List of top k matching log entries
        """
        if self.tfidf_matrix is None or self.embeddings is None:
            print("No logs available for combined search.")
            return []
        
        keyword_results = self.keyword_search(query, k)
        semantic_results = self.semantic_search(query, k)
        
        # Combine results, giving priority to keyword results
        combined_results = keyword_results.copy()
        
        # Add semantic results if they're not already in the combined results
        for result in semantic_results:
            if not any(r.get('id') == result.get('id') for r in combined_results):
                combined_results.append(result)
        
        # Sort combined results by relevance score (assuming higher is better)
        combined_results.sort(key=lambda x: x.get('relevance', 0), reverse=True)
        
        # Return top k results
        return combined_results[:k]

    def add_log(self, log: Dict[str, Any]):
        """
        Add a new log entry to the search index.

        :param log: New log entry to add
        """
        # Add new log to the list
        self.logs.append(log)
        # Update TF-IDF matrix
        self.tfidf_matrix = self.tfidf_vectorizer.fit_transform([log['content'] for log in self.logs])
        # Update embeddings
        self.embeddings = np.vstack([self.embeddings, self.model.encode([log['content']])])