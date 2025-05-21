# penguin/tools/core/memory_search.py
import os
import re
import json
import logging
import uuid
from colorama import Fore, Style, init  # For colored output # type: ignore
from datetime import datetime
from typing import Any, Dict, List, Optional

# Set up logger - will be used for warnings later
logger = logging.getLogger(__name__)

# Move the rest of the imports inside the class to make them lazy

from penguin.config import WORKSPACE_PATH  # Import workspace path from config - this should be fast


class MemorySearcher:
    _instance = None

    def __new__(cls, persist_directory: str = None):
        if cls._instance is None:
            cls._instance = super(MemorySearcher, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, persist_directory: str = None):
        if self._initialized:
            return

        # Import colorama only when needed - moved from top level
        from colorama import Fore, Style, init  # For colored output # type: ignore
        # Initialize colorama
        init()  # For colored output

        # Only attempt to patch SQLite and import ChromaDB and Ollama when actually needed
        try:
            # SQLite patch - moved from top level
            try:
                __import__('pysqlite3')
                import sys
                sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
            except ImportError:
                logger.warning("SQLite Compatibility Warning – chromadb may require the pysqlite3 binary package.")
                logger.warning("Recommended fix: pip install pysqlite3-binary")
                logger.debug("Note: This recommendation comes from user testing (Maximooch)")
            
            # Lazy import ChromaDB - moved from top level
            import chromadb # type: ignore
            from chromadb.config import Settings # type: ignore
        except ImportError as e:
            logger.error(f"Failed to import ChromaDB: {e}")
            raise ImportError(f"ChromaDB is required for memory search functionality: {e}")

        # Set default persist directory to workspace/memory_db if none provided
        if persist_directory is None:
            persist_directory = os.path.join(WORKSPACE_PATH, "memory_db")

        # Ensure directory exists
        os.makedirs(persist_directory, exist_ok=True)

        # Define memory paths relative to workspace
        self.memory_paths = {
            "notes": os.path.join(WORKSPACE_PATH, "notes"),
            "conversations": os.path.join(WORKSPACE_PATH, "conversations"), # Updated paths
        }

        # Initialize ChromaDB client with persistent storage
        try:
            self.client = chromadb.PersistentClient(
                path=persist_directory,
                settings=Settings(
                    anonymized_telemetry=False, allow_reset=True, is_persistent=True
                ),
            )

            # Initialize collections
            self.notes_collection = self.client.get_or_create_collection(
                name="notes",
                metadata={"description": "Declarative notes and documentation"},
            )
            self.conversations_collection = self.client.get_or_create_collection(
                name="conversations", # New collection for conversations
                metadata={"description": "User conversation history"}
            )

            # Try to initialize Ollama client, fall back to simple search if unavailable
            try:
                # Lazy import Ollama - moved from top level
                import ollama # type: ignore
                self.ollama_client = ollama.Client()
                self.use_embeddings = True
            except Exception as e:
                logger.warning(
                    f"Ollama not available, falling back to simple search: {str(e)}"
                )
                self.use_embeddings = False

            # Index existing memories
            self.index_memory_files()

            self._initialized = True

        except Exception as e:
            logger.error(f"Error initializing ChromaDB: {str(e)}")
            raise

    def parse_memory(self, content: str) -> Dict[str, Any]:
        """Parse memory content and extract metadata"""
        memory_info = {
            "timestamp": datetime.now().isoformat(),
            "type": "conversation",
            "summary": "",
        }

        # Try to parse JSON-formatted memories
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                memory_info.update(
                    {
                        "type": data.get("type", "declarative"),
                        "summary": data.get("summary", ""),
                    }
                )
        except json.JSONDecodeError:
            # For plain text, try to extract key information
            lines = content.split("\n")
            if lines:
                memory_info["summary"] = lines[0][:100]  # First line as summary

        return memory_info

    def extract_categories(self, content: str) -> str:
        """Extract categories and join them into a single string"""
        categories = set()

        # Common categories to look for
        category_keywords = {
            "task": ["task", "todo", "done", "complete"],
            "project": ["project", "milestone", "planning"],
            "error": ["error", "bug", "issue", "fix"],
            "decision": ["decision", "chose", "selected", "agreed"],
            "research": ["research", "investigation", "analysis"],
            "code": ["code", "implementation", "function", "class"],
        }

        content_lower = content.lower()
        for category, keywords in category_keywords.items():
            if any(keyword in content_lower for keyword in keywords):
                categories.add(category)

        return ",".join(sorted(categories))  # Convert set to sorted string

    def extract_date_from_path(self, filename: str) -> str:
        """Extract date from filename like chat_20240902_175411.md"""
        match = re.search(r"(\d{8})_(\d{6})", filename)
        if match:
            date = match.group(1)
            time = match.group(2)
            return (
                f"{date[:4]}-{date[4:6]}-{date[6:]}T{time[:2]}:{time[2:4]}:{time[4:]}"
            )
        return datetime.now().isoformat()

    def index_memory(self, content: str, memory_type: str, metadata: Dict[str, Any]):
        """Index a single memory with its metadata"""
        try:
            # Get embeddings if Ollama is available
            if self.use_embeddings:
                try:
                    response = self.ollama_client.embeddings(
                        model="nomic-embed-text", prompt=content
                    )
                    embeddings = [response["embedding"]]
                except Exception as e:
                    logger.warning(
                        f"Error getting embeddings, falling back to null embeddings: {str(e)}"
                    )
                    embeddings = None
            else:
                embeddings = None

            # Ensure all metadata values are strings
            metadata = {k: str(v) for k, v in metadata.items()}

            # Add to appropriate collection
            collection = (
                self.conversations_collection if memory_type == "conversations"
                else self.notes_collection # Default to notes if not conversations
            )
            # Ensure we only add to notes or conversations explicitly
            if memory_type == "notes":
                collection = self.notes_collection
            elif memory_type == "conversations":
                collection = self.conversations_collection
            else:
                logger.warning(f"Attempting to index memory with unhandled type '{memory_type}'. Skipping.")
                return # Don't index if type isn't notes or conversations

            collection.add(
                documents=[content],
                metadatas=[metadata],
                embeddings=embeddings if embeddings else None,
                ids=[str(uuid.uuid4())],
            )
        except Exception as e:
            logger.error(f"Error indexing memory: {str(e)}")

    def index_memory_files(self) -> str:
        """Index all memory files from workspace"""
        try:
            indexed_count = 0
            skipped_count = 0

            # Load previous index metadata
            index_metadata = self._load_index_metadata()
            new_metadata = {}

            # Helper function to check if file needs indexing
            def needs_indexing(file_path: str) -> bool:
                current_meta = self._get_file_metadata(file_path)
                previous_meta = index_metadata.get(file_path)

                if not previous_meta:
                    return True

                return (
                    current_meta["mtime"] != previous_meta["mtime"]
                    or current_meta["size"] != previous_meta["size"]
                )

            # Process each memory type
            for memory_type, base_path in self.memory_paths.items():
                if not os.path.exists(base_path):
                    continue

                for filename in os.listdir(base_path):
                    # Index markdown, text, and JSON files (especially for conversations)
                    # We previously skipped .json files which are the default format for conversation logs.
                    # This prevented the memory search from finding any conversation history.
                    if filename.endswith((".md", ".txt", ".json")):
                        file_path = os.path.join(base_path, filename)

                        # Check if file needs indexing
                        if not needs_indexing(file_path):
                            skipped_count += 1
                            new_metadata[file_path] = index_metadata[file_path]
                            continue

                        # Provide progress feedback occasionally
                        if indexed_count == 0:
                            logger.debug("Memory indexing in progress…")

                        # Index the file
                        with open(file_path, encoding="utf-8") as f:
                            content = f.read()

                            metadata = self.parse_memory(content)
                            metadata.update(
                                {
                                    "file_path": file_path,
                                    "memory_type": memory_type,
                                    "categories": self.extract_categories(content),
                                    "timestamp": self.extract_date_from_path(filename),
                                }
                            )

                            self.index_memory(content, memory_type, metadata)
                            new_metadata[file_path] = self._get_file_metadata(file_path)
                            indexed_count += 1

                            # Show a progress update every 50 indexed files to avoid flooding stdout
                            if verbose := True:  # Future-proof: toggle this to False to silence
                                if indexed_count % 50 == 0:
                                    rel_path = os.path.relpath(file_path, WORKSPACE_PATH)
                                    logger.debug(f"Indexed {indexed_count} files so far (latest: {rel_path})")

            # Save updated metadata
            self._save_index_metadata(new_metadata)

            return f"Indexed {indexed_count} files, skipped {skipped_count} unchanged files"

        except Exception as e:
            logger.error(f"Error during indexing: {str(e)}")
            return f"Indexing failed: {str(e)}"

    def format_preview(self, content: str, max_length: int = 300) -> str:
        """Format the preview text to be more readable"""
        # Remove JSON artifacts and clean up the text
        preview = content.replace("{'assistant_response': '", "")
        preview = preview.replace("'}", "")
        preview = preview.replace('{"assistant_response": "', "")
        preview = preview.replace('"}', "")

        # Truncate with ellipsis if too long
        if len(preview) > max_length:
            preview = preview[:max_length] + "..."

        return preview.strip()

    def search_memory(
        self,
        query: str,
        max_results: int = 5,
        memory_type: Optional[str] = None,
        categories: Optional[List[str]] = None,
        date_after: Optional[str] = None,
        date_before: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search through memory collections"""
        try:
            all_results = []
            collections = []

            # Get embeddings for query if Ollama is available
            query_embedding = None
            if self.use_embeddings:
                try:
                    response = self.ollama_client.embeddings(
                        model="nomic-embed-text", prompt=query
                    )
                    query_embedding = response["embedding"]
                except Exception as e:
                    # If we fail to get embeddings for any reason, log and gracefully fall back
                    logger.warning(
                        f"Falling back to text search due to embedding failure: {str(e)}"
                    )
                    query_embedding = None

            # Determine which collections to search
            if memory_type == "notes":
                collections = [self.notes_collection]
            elif memory_type == "conversations":
                collections = [self.conversations_collection]
            else:
                # If no specific type or an unknown type, search both notes and conversations
                collections = [self.notes_collection, self.conversations_collection]

            # Build where clause
            where = self._build_where_clause(categories, date_after, date_before)

            # Search each collection
            for collection in collections:
                if query_embedding is not None:
                    # Vector based search
                    results = collection.query(
                        query_embeddings=[query_embedding],
                        n_results=max_results,
                        where=where,
                        include=["metadatas", "documents", "distances"],
                    )
                else:
                    # Fallback to simple text search using query_texts
                    results = collection.query(
                        query_texts=[query],
                        n_results=max_results,
                        where=where,
                        include=["metadatas", "documents", "distances"],
                    )

                # Check if we got any results
                if not results["documents"] or not results["documents"][0]:
                    continue

                # Process and format results
                for i in range(len(results["documents"][0])):
                    result = {
                        "metadata": results["metadatas"][0][i],
                        "preview": self.format_preview(results["documents"][0][i]),
                        "relevance": (1 - float(results["distances"][0][i]))
                        * 100,  # Convert distance to similarity score
                        "collection": collection.name,
                    }
                    all_results.append(result)

            # Sort by relevance and limit results
            all_results.sort(key=lambda x: x["relevance"], reverse=True)
            return all_results[:max_results]

        except Exception as e:
            logger.error(f"Error searching memory: {str(e)}")
            return []

    def _build_where_clause(
        self,
        categories: Optional[List[str]],
        date_after: Optional[str],
        date_before: Optional[str],
    ) -> Optional[Dict]:
        """Build the where clause for ChromaDB query"""
        where = {}

        if categories:
            where["categories"] = {"$in": categories}

        if date_after or date_before:
            where["timestamp"] = {}
            if date_after:
                where["timestamp"]["$gte"] = date_after
            if date_before:
                where["timestamp"]["$lte"] = date_before

        return where if where else None

    def wait_for_initialization(self):
        """Wait for ChromaDB initialization to complete"""
        return self._initialized

    def _expand_query_terms(self, query: str) -> str:
        """Expand query with related terms"""
        related_terms = {
            "task": ["todo", "action item", "work item"],
            "refactor": ["restructure", "redesign", "clean up"],
            "bug": ["error", "issue", "problem"],
            "feature": ["functionality", "capability"],
            "test": ["verify", "check", "validate"],
            "automode": [
                "automatic",
                "automated",
                "auto",
                "automation",
                "autonomous",
                "self-running",
                "background",
                "daemon",
                "service",
            ],
            "penguin": ["assistant", "AI", "helper", "bot"],
            "list": ["show", "display", "enumerate", "output"],
        }

        expanded = query
        for term, synonyms in related_terms.items():
            if term.lower() in query.lower():
                expanded += f" {' '.join(synonyms)}"

        print(f"\nDebug: Expanded query: {expanded}")
        return expanded

    def _calculate_content_hash(self, content: str) -> str:
        """Create a fuzzy hash of content for deduplication"""
        # Simplified version - could use better fuzzy matching
        words = content.lower().split()[:20]  # First 20 words
        return " ".join(words)

    def _calculate_relevance(self, doc: str, query: str, score: float) -> float:
        """Enhanced relevance calculation"""
        base_score = max(0, min(100, (1 - score) * 100))

        # Boost exact matches
        content_lower = doc.lower()
        query_terms = query.lower().split()
        exact_matches = sum(term in content_lower for term in query_terms)
        base_score += exact_matches * 10

        # Boost recent content
        try:
            doc_date = datetime.fromisoformat(doc.split("(")[1].split(")")[0])
            days_old = (datetime.now() - doc_date).days
            recency_boost = max(
                0, 10 - (days_old / 30)
            )  # Up to 10 points for newer content
            base_score += recency_boost
        except:
            pass

        return min(100, base_score)

    def _get_highlights(self, text: str, query: str) -> List[tuple]:
        """Find positions of terms to highlight"""
        highlights = []
        query_terms = set(query.lower().split())

        for term in query_terms:
            for match in re.finditer(rf"\b{re.escape(term)}\b", text.lower()):
                highlights.append((match.start(), match.end()))

        return highlights

    def _extract_relevant_preview(
        self, content: str, query: str, max_length: int = 300
    ) -> str:
        """Extract a relevant preview that includes query context"""
        # Split into messages by markdown headers
        messages = []
        current_message = []

        for line in content.split("\n"):
            if line.startswith("###"):
                if current_message:
                    messages.append("\n".join(current_message))
                current_message = [line]
            else:
                current_message.append(line)

        if current_message:
            messages.append("\n".join(current_message))

        def clean_message(msg):
            """Clean up a message for display"""
            # Extract assistant response from JSON-like format
            if "assistant_response" in msg:
                match = re.search(r"'assistant_response':\s*'([^']+)'", msg)
                if match:
                    return match.group(1)
            # Clean up user input
            if "User input:" in msg:
                return msg.split("User input:", 1)[1].strip()
            return msg.strip()

        # First try: find messages containing query terms
        query_terms = query.lower().split()
        relevant_messages = []

        for msg in messages:
            msg_lower = msg.lower()
            if any(term in msg_lower for term in query_terms):
                cleaned = clean_message(msg)
                if cleaned:
                    relevant_messages.append(cleaned)

        if relevant_messages:
            # Show the most relevant message and its context
            best_idx = 0  # Index of most relevant message
            start_idx = max(0, best_idx - 1)
            end_idx = min(len(relevant_messages), best_idx + 2)
            preview = "\n   ".join(relevant_messages[start_idx:end_idx])
            return (
                preview[:max_length] + "..." if len(preview) > max_length else preview
            )

        # Fallback: Show a conversation exchange (user + assistant if possible)
        for i, msg in enumerate(messages):
            if "👤 User" in msg:
                user_msg = clean_message(msg)
                # Try to get the assistant's response
                if i + 1 < len(messages) and "🐧 Penguin" in messages[i + 1]:
                    assistant_msg = clean_message(messages[i + 1])
                    return f"{user_msg}\n   {assistant_msg}"[:max_length] + "..."
                return user_msg[:max_length] + "..."

        # Final fallback: Just show the first non-empty message
        for msg in messages:
            cleaned = clean_message(msg)
            if cleaned:
                return cleaned[:max_length] + "..."

        return "Empty conversation"

    def _format_results(self, results, query: str) -> List[Dict[str, Any]]:
        """Format search results into a clean structure with relevant previews"""
        combined_results = []
        if not results["ids"]:
            return combined_results

        for doc, meta, distance in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            preview = self._extract_relevant_preview(doc, query)
            combined_results.append(
                {
                    "content": doc,
                    "metadata": meta,
                    "distance": distance,
                    "preview": preview,
                }
            )

        return combined_results

    def _get_file_metadata(self, file_path: str) -> Dict[str, Any]:
        """Get file metadata including modification time"""
        stat = os.stat(file_path)
        return {"path": file_path, "mtime": stat.st_mtime, "size": stat.st_size}

    def _load_index_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Load metadata of previously indexed files"""
        metadata_path = os.path.join(WORKSPACE_PATH, "memory_db", "index_metadata.json")
        try:
            if os.path.exists(metadata_path):
                with open(metadata_path) as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load index metadata: {e}")
        return {}

    def _save_index_metadata(self, metadata: Dict[str, Dict[str, Any]]):
        """Save metadata of indexed files"""
        metadata_path = os.path.join(WORKSPACE_PATH, "memory_db", "index_metadata.json")
        try:
            os.makedirs(os.path.dirname(metadata_path), exist_ok=True)
            with open(metadata_path, "w") as f:
                json.dump(metadata, f)
        except Exception as e:
            logger.warning(f"Failed to save index metadata: {e}")


def print_results(results: List[Dict[str, Any]]):
    """Print results with colored highlighting"""
    if not results:
        print("\nNo results found.")
        return

    print("\nSearch Results:")
    print("---------------")

    for i, result in enumerate(results, 1):
        print(f"\n{i}. From: {result['metadata']['file_path']}")
        print(f"   Type: {result['metadata']['memory_type']}")
        print(f"   Categories: {result['metadata']['categories']}")
        print(f"   Relevance: {result['relevance']:.2f}/100")
        print("   Preview:")

        # Print with highlights
        text = result["preview"]
        last_pos = 0
        for start, end in sorted(result["highlights"]):
            print(f"   {text[last_pos:start]}", end="")
            print(f"{Fore.YELLOW}{text[start:end]}{Style.RESET_ALL}", end="")
            last_pos = end
        print(f"   {text[last_pos:]}")


if __name__ == "__main__":
    searcher = MemorySearcher()

    print("\nPenguin Memory Search")
    print("===================")

    # Index files first
    searcher.index_memory_files()

    # Interactive search loop
    while True:
        try:
            query = input("\nEnter search query (or 'exit' to quit): ").strip()
            if query.lower() == "exit":
                break

            memory_type = (
                input("Filter by type (notes/conversations, Enter to skip): ").strip() or None
            )
            categories_input = input(
                "Filter by categories (comma-separated, Enter to skip): "
            ).strip()
            categories = (
                [c.strip() for c in categories_input.split(",")]
                if categories_input
                else None
            )

            date_after_input = input(
                "Filter by date after (YYYY-MM-DD, Enter to skip): "
            ).strip()
            date_after = (
                datetime.fromisoformat(date_after_input) if date_after_input else None
            )

            date_before_input = input(
                "Filter by date before (YYYY-MM-DD, Enter to skip): "
            ).strip()
            date_before = (
                datetime.fromisoformat(date_before_input) if date_before_input else None
            )

            results = searcher.search_memory(
                query=query,
                max_results=5,
                memory_type=memory_type,
                categories=categories,
                date_after=date_after,
                date_before=date_before,
            )

            if not results:
                print("\nNo results found.")
                continue

            print("\nSearch Results:")
            print("---------------")
            for i, result in enumerate(results, 1):
                print(f"\n{i}. From: {result['metadata']['file_path']}")
                print(f"   Type: {result['metadata']['memory_type']}")
                print(f"   Categories: {result['metadata']['categories']}")
                print(f"   Relevance: {result['relevance']:.2f}/100")
                print("   Preview:")
                print(f"   {result['preview']}")

        except KeyboardInterrupt:
            print("\nSearch interrupted.")
            break
        except Exception as e:
            print(f"\nError during search: {str(e)}")
            continue

    print("\nSearch interface closed.")
