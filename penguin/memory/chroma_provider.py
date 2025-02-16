import uuid
from typing import Any, Dict, List, Optional

import chromadb  # type: ignore
import torch  # type: ignore
from chromadb.config import Settings  # type: ignore
from transformers import AutoModel, AutoTokenizer  # type: ignore

from .provider import MemoryProvider


class ChromaProvider(MemoryProvider):
    def __init__(
        self,
        persist_directory: str = "./chroma_db",
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    ):
        self.client = chromadb.Client(
            Settings(persist_directory=persist_directory, anonymized_telemetry=False)
        )
        self.memory_collection = self.client.get_or_create_collection("memory")
        self.code_collection = self.client.get_or_create_collection("code")

        # Initialize HuggingFace model and tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name)

    def _get_embedding(self, text: str) -> List[float]:
        inputs = self.tokenizer(
            text, return_tensors="pt", truncation=True, max_length=512, padding=True
        )
        with torch.no_grad():
            outputs = self.model(**inputs)
        embeddings = outputs.last_hidden_state.mean(dim=1).squeeze().tolist()
        return embeddings

    def add_memory(
        self, content: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        memory_id = str(uuid.uuid4())
        embedding = self._get_embedding(content)
        self.memory_collection.add(
            documents=[content],
            metadatas=[metadata or {}],
            ids=[memory_id],
            embeddings=[embedding],
        )
        return memory_id

    def search_memory(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        query_embedding = self._get_embedding(query)
        results = self.memory_collection.query(
            query_embeddings=[query_embedding], n_results=max_results
        )
        return [
            {"content": doc, "metadata": meta, "id": id}
            for doc, meta, id in zip(
                results["documents"][0], results["metadatas"][0], results["ids"][0]
            )
        ]

    def add_code(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        code_id = str(uuid.uuid4())
        embedding = self._get_embedding(content)
        self.code_collection.add(
            documents=[content],
            metadatas=[metadata or {}],
            ids=[code_id],
            embeddings=[embedding],
        )
        return code_id

    def search_code(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        query_embedding = self._get_embedding(query)
        results = self.code_collection.query(
            query_embeddings=[query_embedding], n_results=max_results
        )
        return [
            {"content": doc, "metadata": meta, "id": id}
            for doc, meta, id in zip(
                results["documents"][0], results["metadatas"][0], results["ids"][0]
            )
        ]

    def format_results(self, results: List[Dict[str, Any]]) -> str:
        formatted = []
        for i, result in enumerate(results, 1):
            formatted.append(f"{i}. Content: {result['content'][:100]}...")
            if result.get("metadata"):
                formatted.append(f"   Metadata: {result['metadata']}")
            formatted.append(f"   ID: {result['id']}")
            formatted.append("")
        return "\n".join(formatted)
