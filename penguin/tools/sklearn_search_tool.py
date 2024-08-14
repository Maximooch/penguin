from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import os
import logging
from typing import List, Dict, Union
import numpy as np
import scipy.sparse

class SklearnSearch:
    def __init__(self, root_dir: str = '.', file_types: List[str] = None):
        self.root_dir = root_dir
        self.file_types = file_types or ['.py', '.md', '.txt']
        self.documents = []
        self.vectorizer = TfidfVectorizer(lowercase=True)
        self.tfidf_matrix = None
        self.index_files()

    def index_files(self):
        for root, _, files in os.walk(self.root_dir):
            for file in files:
                if any(file.endswith(ft) for ft in self.file_types):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            self.documents.append({
                                'type': 'file',
                                'path': file_path,
                                'content': content
                            })
                    except Exception as e:
                        logging.error(f"Error reading file {file_path}: {str(e)}")
        self._update_tfidf()

    def add_message(self, message: Dict[str, str]):
        self.documents.append({
            'type': 'message',
            'content': message['content'],
            'role': message.get('role', 'user')
        })
        self._update_tfidf(incremental=True)

    def _update_tfidf(self, incremental=False):
        corpus = [doc['content'] for doc in self.documents]
        if incremental and self.tfidf_matrix is not None:
            new_tfidf = self.vectorizer.transform([corpus[-1]])
            if isinstance(self.tfidf_matrix, np.ndarray):
                self.tfidf_matrix = np.vstack((self.tfidf_matrix, new_tfidf.toarray()))
            else:
                self.tfidf_matrix = scipy.sparse.vstack((self.tfidf_matrix, new_tfidf))
        else:
            self.tfidf_matrix = self.vectorizer.fit_transform(corpus)

    def search(self, query: Union[str, List[str]], k: int = 5, case_sensitive: bool = False, search_files: bool = True, search_messages: bool = True) -> List[Dict[str, str]]:
        if isinstance(query, list):
            query = ' '.join(query)
        
        if not case_sensitive:
            query = query.lower()
        
        query_vector = self.vectorizer.transform([query])
        cosine_similarities = cosine_similarity(query_vector, self.tfidf_matrix).flatten()
        
        top_indices = cosine_similarities.argsort()[-k*3:][::-1]  # Get more initial results
        
        results = []
        for idx in top_indices:
            doc = self.documents[idx]
            if (search_files and doc['type'] == 'file') or (search_messages and doc['type'] == 'message'):
                # Calculate the number of query terms present in the document
                query_terms = set(query.lower().split())
                doc_terms = set(doc['content'].lower().split())
                matching_terms = query_terms.intersection(doc_terms)
                
                # Calculate fuzzy match ratio
                fuzzy_ratio = self._fuzzy_match_ratio(query.lower(), doc['content'].lower())
                
                # Calculate relevance score
                relevance_score = (
                    0.4 * cosine_similarities[idx] +
                    0.3 * (len(matching_terms) / len(query_terms)) +
                    0.3 * fuzzy_ratio
                )
                
                if relevance_score > 0.5:
                    results.append({
                        'content': doc['content'],
                        'type': doc['type'],
                        'path': doc.get('path'),
                        'role': doc.get('role'),
                        'relevance_score': relevance_score,
                        'cosine_similarity': cosine_similarities[idx],
                        'matching_terms': len(matching_terms),
                        'fuzzy_ratio': fuzzy_ratio
                    })
            
            if len(results) == k:
                break
        
        # Sort results by relevance score
        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        return results[:k]

    def _fuzzy_match_ratio(self, s1: str, s2: str) -> float:
        # Simple fuzzy matching using character-level similarity
        s1_set = set(s1)
        s2_set = set(s2)
        return len(s1_set.intersection(s2_set)) / len(s1_set.union(s2_set))

    def update_index(self):
        self.documents = []
        self.index_files()

    def clear_messages(self):
        self.documents = [doc for doc in self.documents if doc['type'] == 'file']
        self._update_tfidf()