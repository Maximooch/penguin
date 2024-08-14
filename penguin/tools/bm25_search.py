import os
from rank_bm25 import BM25Okapi
from typing import List, Dict

class BM25Search:
    def __init__(self, root_dir: str = '.'):
        self.messages: List[Dict[str, str]] = []
        self.file_contents: List[Dict[str, str]] = []
        self.bm25 = None
        self.root_dir = root_dir
        self.index_files()

    def index_files(self):
        for root, _, files in os.walk(self.root_dir):
            for file in files:
                if file.endswith(('.py', '.md', '.txt')):  # Add more file types if needed
                    file_path = os.path.join(root, file)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        self.file_contents.append({
                            'path': file_path,
                            'content': content
                        })
        self._update_bm25()

    def add_message(self, message: Dict[str, str]):
        self.messages.append(message)
        self._update_bm25()

    def _update_bm25(self):
        all_documents = [msg['content'] for msg in self.messages] + [file['content'] for file in self.file_contents]
        tokenized_corpus = [doc.split() for doc in all_documents]
        self.bm25 = BM25Okapi(tokenized_corpus)

    def search(self, query: str, k: int = 5) -> List[Dict[str, str]]:
        if not self.bm25:
            return []
        tokenized_query = query.split()
        doc_scores = self.bm25.get_scores(tokenized_query)
        top_n = sorted(range(len(doc_scores)), key=lambda i: doc_scores[i], reverse=True)[:k]
        
        results = []
        for i in top_n:
            if i < len(self.messages):
                results.append(self.messages[i])
            else:
                file_index = i - len(self.messages)
                results.append({
                    'role': 'file',
                    'content': f"File: {self.file_contents[file_index]['path']}\n{self.file_contents[file_index]['content'][:500]}..."
                })
        return results