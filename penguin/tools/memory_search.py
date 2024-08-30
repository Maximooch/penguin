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
        # Initialize TF-IDF vectorizer for keyword search
        self.tfidf_vectorizer = TfidfVectorizer()
        self.tfidf_matrix = self.tfidf_vectorizer.fit_transform([log['content'] for log in self.logs])
        # Initialize sentence transformer model for semantic search
        self.model = SentenceTransformer('paraphrase-MiniLM-L3-v2')
        self.embeddings = self.compute_embeddings()

    def load_logs(self) -> List[Dict[str, Any]]:
        """
        Load all JSON log files from the log directory.

        :return: List of log entries
        """
        logs = []
        for filename in os.listdir(self.log_dir):
            if filename.endswith('.json'):
                with open(os.path.join(self.log_dir, filename), 'r') as f:
                    logs.extend(json.load(f))
        return logs

    def compute_embeddings(self) -> np.ndarray:
        """
        Compute embeddings for all log entries using the sentence transformer model.

        :return: numpy array of embeddings
        """
        return self.model.encode([log['content'] for log in self.logs])

    def keyword_search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Perform keyword-based search using TF-IDF and cosine similarity.

        :param query: Search query
        :param k: Number of top results to return
        :return: List of top k matching log entries
        """
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
        # Get results from both search methods
        keyword_results = self.keyword_search(query, k)
        semantic_results = self.semantic_search(query, k)
        
        # Combine results and remove duplicates
        combined = keyword_results + semantic_results
        unique_results = {r['timestamp']: r for r in combined}.values()
        
        # Sort results by similarity score or timestamp
        sorted_results = sorted(
            unique_results,
            key=lambda x: x.get('similarity', 0) if x.get('similarity') is not None else x['timestamp'],
            reverse=True
        )
        
        return sorted_results[:k]

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