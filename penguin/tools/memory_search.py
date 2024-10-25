import os
import json
from typing import List, Dict, Any
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from sentence_transformers import SentenceTransformer
import scipy.sparse
import pickle
import logging
from threading import Lock, Event, Thread
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class MemorySearch:
    """
    A class for searching and managing log entries using both keyword and semantic search methods.
    """

    def __init__(self, log_dir: str = 'logs', embeddings_dir: str = 'embeddings'):
        self.log_dir = os.path.abspath(log_dir)
        self.embeddings_dir = os.path.abspath(embeddings_dir)
        os.makedirs(self.embeddings_dir, exist_ok=True)
        self.logs = None  # Defer loading
        self.lock = Lock()
        self.tfidf_vectorizer = None
        self.tfidf_matrix = None
        self.model = None
        self.embeddings = None
        self.initialization_complete = Event()
        Thread(target=self.background_initialize, daemon=True).start()

    def background_initialize(self):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.ensure_logs_loaded()
                if not self.logs:
                    logger.warning("No logs found. Skipping model initialization.")
                    self.initialization_complete.set()
                    return
                self.ensure_models_loaded()
                self.save_models()
                self.initialization_complete.set()
                logger.info("Memory search initialization completed successfully.")
                return
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(1)  # Wait for 1 second before retrying
        logger.error("Memory search initialization failed after all attempts.")

    def wait_for_initialization(self):
        """
        Wait until the logs and models are fully initialized.
        """
        if not self.initialization_complete.is_set():
            logger.info("Initializing memory search models, please wait...")
            self.initialization_complete.wait()
        logger.info("Memory search initialization completed.")

    def ensure_logs_loaded(self):
        if self.logs is None:
            self.logs = self.load_logs()

    def ensure_models_loaded(self):
        if self.tfidf_vectorizer is None or self.tfidf_matrix is None:
            self.load_or_initialize_models()

    def load_or_initialize_models(self):
        # Always re-initialize models to include recent logs
        self.initialize_models()

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
                        file_logs = json.load(f)
                        # Ensure each log entry has a 'content' field that's a string
                        for log in file_logs:
                            if isinstance(log, dict):
                                if 'content' not in log:
                                    log['content'] = str(log)
                                elif not isinstance(log['content'], str):
                                    log['content'] = str(log['content'])
                                logs.append(log)
            # Sort logs by timestamp to ensure they are in chronological order
            logs.sort(key=lambda x: x.get('timestamp', ''))
        except FileNotFoundError:
            logger.warning(f"Log directory '{self.log_dir}' not found.")
        except Exception as e:
            logger.error(f"Error loading logs: {e}")
        return logs

    def initialize_models(self):
        """
        Initialize models when no saved data is available or to update with recent logs.
        """
        if not self.logs:
            logger.warning("No logs available for model initialization.")
            return
        self.tfidf_vectorizer = TfidfVectorizer()
        self.tfidf_matrix = self.tfidf_vectorizer.fit_transform([log['content'] for log in self.logs])
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.embeddings = self.compute_embeddings()

    def save_models(self):
        """
        Save models and data to disk.
        """
        try:
            os.makedirs(self.embeddings_dir, exist_ok=True)
            with open(os.path.join(self.embeddings_dir, 'tfidf_vectorizer.pkl'), 'wb') as f:
                pickle.dump(self.tfidf_vectorizer, f)
            if self.tfidf_matrix is not None:
                scipy.sparse.save_npz(os.path.join(self.embeddings_dir, 'tfidf_matrix.npz'), self.tfidf_matrix)
            if self.embeddings is not None and len(self.embeddings) > 0:
                np.save(os.path.join(self.embeddings_dir, 'embeddings.npy'), self.embeddings)
            logger.info(f"Models saved successfully to {self.embeddings_dir}")
        except Exception as e:
            logger.error(f"Error saving models: {str(e)}")

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
        self.wait_for_initialization()
        self.ensure_logs_loaded()
        self.ensure_models_loaded()
        if self.tfidf_matrix is None:
            logger.warning("No logs available for keyword search.")
            return []
        
        query_vec = self.tfidf_vectorizer.transform([query])
        similarities = cosine_similarity(query_vec, self.tfidf_matrix)[0]
        top_k_indices = similarities.argsort()[-k:][::-1]
        return self.format_search_results(top_k_indices)

    def semantic_search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Perform semantic search using sentence embeddings and cosine similarity.

        :param query: Search query
        :param k: Number of top results to return
        :return: List of top k matching log entries
        """
        self.wait_for_initialization()
        self.ensure_logs_loaded()
        self.ensure_models_loaded()
        if self.embeddings is None:
            logger.warning("No logs available for semantic search.")
            return []
        
        query_embedding = self.model.encode([query])
        similarities = cosine_similarity(query_embedding, self.embeddings)[0]
        top_k_indices = similarities.argsort()[-k:][::-1]
        return self.format_search_results(top_k_indices)

    def combined_search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Perform both keyword and semantic search, combine results, and return top k unique entries.

        :param query: Search query
        :param k: Number of top results to return
        :return: List of top k matching log entries
        """
        self.wait_for_initialization()
        if self.tfidf_matrix is None or self.embeddings is None:
            logger.warning("No logs available for combined search.")
            return []
        
        keyword_scores = cosine_similarity(self.tfidf_vectorizer.transform([query]), self.tfidf_matrix)[0]
        semantic_scores = cosine_similarity(self.model.encode([query]), self.embeddings)[0]
        
        # Normalize scores
        keyword_scores = (keyword_scores - np.min(keyword_scores)) / (np.max(keyword_scores) - np.min(keyword_scores))
        semantic_scores = (semantic_scores - np.min(semantic_scores)) / (np.max(semantic_scores) - np.min(semantic_scores))
        
        # Combine scores with equal weighting
        combined_scores = 0.5 * keyword_scores + 0.5 * semantic_scores
        
        top_k_indices = combined_scores.argsort()[-k:][::-1]
        return self.format_search_results(top_k_indices)

    def format_search_results(self, indices: List[int]) -> List[Dict[str, Any]]:
        """
        Format search results with proper timestamps and content.

        :param indices: List of indices of top matching log entries
        :return: List of formatted log entries
        """
        results = []
        for i in indices:
            log_entry = self.logs[i]
            timestamp_str = log_entry.get('timestamp', 'Unknown')
            try:
                # Parse timestamp to datetime object for accurate sorting
                timestamp = datetime.fromisoformat(timestamp_str)
                formatted_timestamp = timestamp.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                logger.warning(f"Invalid timestamp format: {timestamp_str}")
                formatted_timestamp = timestamp_str

            content = log_entry.get('content', '')
            # Remove line numbers from content if present
            content = '\n'.join([line.split('|', 1)[-1] if '|' in line else line for line in content.split('\n')])
            results.append({
                "timestamp": formatted_timestamp,
                "content": content
            })
        
        # Sort results by timestamp, most recent first
        return sorted(results, key=lambda x: x['timestamp'], reverse=True)

    def add_log(self, log: Dict[str, Any]):
        """
        Add a new log entry to the search index.

        :param log: New log entry to add
        """
        with self.lock:
            # Add new log to the list
            self.logs.append(log)
            
            # Update TF-IDF matrix incrementally
            new_tfidf_vec = self.tfidf_vectorizer.transform([log['content']])
            self.tfidf_matrix = scipy.sparse.vstack([self.tfidf_matrix, new_tfidf_vec])
            
            # Update embeddings incrementally
            new_embedding = self.model.encode([log['content']])
            self.embeddings = np.vstack([self.embeddings, new_embedding])
            
            # Save updated models
            self.save_models()
            
        logger.info(f"New log entry added and models updated.")

    def update_logs(self):
        """
        Update logs with any new entries and rebuild models.
        """
        new_logs = self.load_logs()
        if len(new_logs) > len(self.logs):
            self.logs = new_logs
            self.initialize_models()
            self.save_models()
            logger.info("Logs updated and models rebuilt.")
        else:
            logger.info("No new logs found.")
