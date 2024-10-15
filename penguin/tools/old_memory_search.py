import os
import json
from typing import List, Dict, Any
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from sentence_transformers import SentenceTransformer
import scipy.sparse
import pickle
import logging
from threading import Lock, Event, Thread
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class MemorySearch:
    """
    A class for searching and managing log entries using both keyword and semantic search methods.
    """

    def __init__(self, log_dir: str = 'logs', embeddings_dir: str = 'embeddings', model_name: str = 'all-MiniLM-L6-v2'):
        """
        Initialize the MemorySearch object without loading logs or models.
        Start the background initialization thread.
        """
        self.log_dir = os.path.abspath(log_dir)
        self.embeddings_dir = os.path.abspath(embeddings_dir)
        os.makedirs(self.embeddings_dir, exist_ok=True)  # Ensure the directory exists
        self.logs = None  # Defer loading
        self.lock = Lock()
        self.tfidf_vectorizer = HashingVectorizer(alternate_sign=False)
        self.tfidf_matrix = None
        self.model = None
        self.embeddings = None
        self.initialization_complete = Event()
        init_thread = Thread(target=self.background_initialize, daemon=True)
        init_thread.start()
        self.initialization_complete.wait()  # Wait for initialization
        self.save_interval = 10
        self.change_counter = 0
        self.model_name = model_name

    def background_initialize(self):
        self.ensure_logs_loaded()
        self.ensure_models_loaded()
        self.save_models()
        self.initialization_complete.set()

    def wait_for_initialization(self):
        """
        Wait until the logs and models are fully initialized.
        """
        if not self.initialization_complete.is_set():
            logger.info("Initializing models, please wait...")
            self.initialization_complete.wait()

    def ensure_logs_loaded(self):
        if self.logs is None:
            self.logs = self.load_logs()

    def ensure_models_loaded(self):
        if self.tfidf_vectorizer is None or self.tfidf_matrix is None:
            self.load_or_initialize_models()

    def load_or_initialize_models(self):
        # Try to load models
        try:
            self.load_models()
        except FileNotFoundError:
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
                        content = json.load(f)
                        if isinstance(content, list):
                            logs.extend(content)
                        elif isinstance(content, dict):
                            logs.append(content)
                        else:
                            logger.warning(f"Unsupported log format in file {filename}.")
        except FileNotFoundError:
            logger.warning(f"Log directory '{self.log_dir}' not found.")
        except Exception as e:
            logger.error(f"Error loading logs: {e}")
        return logs

    def load_models(self):
        """
        Load serialized models and data from disk.
        """
        try:
            if not os.path.exists(self.embeddings_dir):
                logger.info(f"Embeddings directory {self.embeddings_dir} does not exist. Initializing new models.")
                raise FileNotFoundError

            with open(os.path.join(self.embeddings_dir, 'tfidf_vectorizer.pkl'), 'rb') as f:
                self.tfidf_vectorizer = pickle.load(f)
            self.tfidf_matrix = scipy.sparse.load_npz(os.path.join(self.embeddings_dir, 'tfidf_matrix.npz'))
            self.embeddings = np.load(os.path.join(self.embeddings_dir, 'embeddings.npy'), mmap_mode='r')
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Models loaded successfully.")
        except FileNotFoundError:
            logger.info("No saved models found. Initializing new models.")
            raise
        except Exception as e:
            logger.error(f"Error loading models: {e}")
            raise

    def initialize_models(self):
        """
        Initialize models when no saved data is available.
        """
        self.tfidf_matrix = self.tfidf_vectorizer.fit_transform([log['content'] for log in self.logs])
        try:
            self.model = SentenceTransformer(self.model_name)
        except Exception as e:
            logger.error(f"Error loading model '{self.model_name}': {e}")
            raise
        self.embeddings = self.compute_embeddings()

    def save_models(self):
        """
        Save models and data to disk.
        """
        try:
            with open(os.path.join(self.embeddings_dir, 'tfidf_vectorizer.pkl'), 'wb') as f:
                pickle.dump(self.tfidf_vectorizer, f)
            
            if self.tfidf_matrix is not None:
                scipy.sparse.save_npz(os.path.join(self.embeddings_dir, 'tfidf_matrix.npz'), self.tfidf_matrix)
            
            if self.embeddings is not None:
                np.save(os.path.join(self.embeddings_dir, 'embeddings.npy'), self.embeddings)
            
            logger.info("Models saved successfully.")
        except Exception as e:
            logger.error(f"Error saving models: {str(e)}")
            raise

    def compute_embeddings(self) -> np.ndarray:
        """
        Compute embeddings for all log entries using the sentence transformer model.

        :return: numpy array of embeddings
        """
        if not self.logs:
            return np.array([])
        return self.model.encode([log['content'] for log in self.logs])

    @contextmanager
    def read_lock(self):
        self.lock.acquire()
        try:
            yield
        finally:
            self.lock.release()

    def keyword_search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Perform keyword-based search using TF-IDF and cosine similarity.

        :param query: Search query
        :param k: Number of top results to return
        :return: List of top k matching log entries
        """
        with self.read_lock():
            self.wait_for_initialization()
            self.ensure_logs_loaded()
            self.ensure_models_loaded()
            if self.tfidf_matrix is None:
                logger.warning("No logs available for keyword search.")
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
        with self.read_lock():
            self.wait_for_initialization()
            self.ensure_logs_loaded()
            self.ensure_models_loaded()
            if self.embeddings is None:
                logger.warning("No logs available for semantic search.")
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
        with self.read_lock():
            self.wait_for_initialization()
            if self.tfidf_matrix is None or self.embeddings is None:
                logger.warning("No logs available for combined search.")
                return []
            
            keyword_scores = cosine_similarity(self.tfidf_vectorizer.transform([query]), self.tfidf_matrix)[0]
            semantic_scores = cosine_similarity(self.model.encode([query]), self.embeddings)[0]
            
            # Normalize scores with zero division check
            def normalize(scores):
                min_score = np.min(scores)
                max_score = np.max(scores)
                if max_score - min_score == 0:
                    return np.zeros_like(scores)
                return (scores - min_score) / (max_score - min_score)
            
            keyword_scores = normalize(keyword_scores)
            semantic_scores = normalize(semantic_scores)
            
            # Combine scores with equal weighting
            combined_scores = 0.5 * keyword_scores + 0.5 * semantic_scores
            
            top_k_indices = combined_scores.argsort()[-k:][::-1]
            return [self.logs[i] for i in top_k_indices]

    def add_log(self, log: Dict[str, Any]):
        """
        Add a new log entry to the search index.

        :param log: New log entry to add
        """
        with self.lock:
            # Add new log to the list
            self.logs.append(log)
            
            # Recompute the TF-IDF matrix
            self.tfidf_matrix = self.tfidf_vectorizer.transform([entry['content'] for entry in self.logs])
            
            # Update embeddings incrementally
            new_embedding = self.model.encode([log['content']])
            if self.embeddings is None or len(self.embeddings) == 0:
                self.embeddings = new_embedding
            else:
                self.embeddings = np.vstack([self.embeddings, new_embedding])
            
            # Save updated models
            self.change_counter += 1
            if self.change_counter >= self.save_interval:
                self.save_models()
                self.change_counter = 0
            
        logger.info(f"New log entry added and models updated.")