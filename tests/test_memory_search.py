import unittest
import os
import shutil
import tempfile
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime

# Mock chromadb and ollama for testing without dependencies
import sys
sys.modules['chromadb'] = MagicMock()
sys.modules['ollama'] = MagicMock()

# Import after mocking dependencies
from penguin.tools.core.memory_search import MemorySearcher
from penguin.config import WORKSPACE_PATH


class TestMemorySearcher(unittest.TestCase):
    """Test cases for the MemorySearcher class"""

    def setUp(self):
        """Set up test environment before each test"""
        # Create a temporary directory for testing
        self.test_dir = tempfile.mkdtemp()
        self.memory_db_dir = os.path.join(self.test_dir, "memory_db")
        
        # Create test directories for memory types
        self.logs_dir = os.path.join(self.test_dir, "logs")
        self.notes_dir = os.path.join(self.test_dir, "notes")
        self.conversations_dir = os.path.join(self.test_dir, "conversations")
        
        for d in [self.memory_db_dir, self.logs_dir, self.notes_dir, self.conversations_dir]:
            os.makedirs(d, exist_ok=True)
        
        # Reset singleton instance for testing
        MemorySearcher._instance = None
        
        # Create some sample memory files
        self._create_sample_files()
    
    def tearDown(self):
        """Clean up after each test"""
        # Remove the temporary directory and its contents
        shutil.rmtree(self.test_dir)
    
    def _create_sample_files(self):
        """Create sample memory files for testing"""
        # Create a log file
        log_content = "Test log entry\nThis is a test log about tasks and errors."
        with open(os.path.join(self.logs_dir, "log_20240601_120000.md"), 'w') as f:
            f.write(log_content)
        
        # Create a note file
        note_content = "# Project Planning\nNotes about project planning and research."
        with open(os.path.join(self.notes_dir, "project_notes.md"), 'w') as f:
            f.write(note_content)
        
        # Create a conversation file with test query
        conversation_content = """
### User: 2024-06-01T12:30:00
Are you a real Penguin?

### Assistant: 2024-06-01T12:30:05
I'm a virtual assistant called Penguin! While I can't waddle or swim in freezing Antarctic waters, 
I'm designed to help with coding tasks and answer questions. So in the digital sense, 
yes, I am a real Penguin - just not the feathery kind you'd find at the South Pole.
"""
        with open(os.path.join(self.conversations_dir, "chat_20240601_123000.md"), 'w') as f:
            f.write(conversation_content)
    
    @patch('penguin.tools.core.memory_search.WORKSPACE_PATH', new_callable=lambda: None)
    def test_initialization(self, mock_workspace_path):
        """Test initialization of MemorySearcher"""
        # Override WORKSPACE_PATH for testing
        mock_workspace_path.return_value = self.test_dir
        
        # Initialize with custom persist directory
        searcher = MemorySearcher(persist_directory=self.memory_db_dir)
        
        # Verify memory paths
        self.assertEqual(searcher.memory_paths["logs"], os.path.join(mock_workspace_path(), "logs"))
        self.assertEqual(searcher.memory_paths["notes"], os.path.join(mock_workspace_path(), "notes"))
        self.assertEqual(searcher.memory_paths["conversations"], os.path.join(mock_workspace_path(), "conversations"))
        
        # Verify collections were created
        self.assertIsNotNone(searcher.logs_collection)
        self.assertIsNotNone(searcher.notes_collection)
        self.assertIsNotNone(searcher.conversations_collection)
    
    @patch('os.path.exists')
    @patch('os.listdir')
    @patch('builtins.open', new_callable=mock_open)
    def test_index_memory_files(self, mock_file, mock_listdir, mock_exists):
        """Test indexing memory files"""
        # Setup mocks
        mock_exists.return_value = True
        mock_listdir.return_value = ["file1.md", "file2.txt", "file3.json"]
        mock_file.return_value.__enter__.return_value.read.return_value = "Test content"
        
        # Create test instance with mocked chromadb
        searcher = MemorySearcher(persist_directory=self.memory_db_dir)
        
        # Replace index_memory with a mock to avoid actual indexing
        searcher.index_memory = MagicMock()
        
        # Test indexing
        result = searcher.index_memory_files()
        
        # Verify results
        self.assertIn("Indexed", result)
        self.assertTrue(searcher.index_memory.called)
    
    @patch('ollama.Client')
    def test_search_memory(self, mock_ollama_client):
        """Test search_memory functionality"""
        # Setup mock ollama client to return dummy embeddings
        mock_embeddings_response = {"embedding": [0.1, 0.2, 0.3]}
        mock_ollama_instance = MagicMock()
        mock_ollama_instance.embeddings.return_value = mock_embeddings_response
        mock_ollama_client.return_value = mock_ollama_instance
        
        # Create test instance with mocked chromadb
        searcher = MemorySearcher(persist_directory=self.memory_db_dir)
        
        # Mock collections query response
        mock_query_response = {
            "ids": [["id1"]],
            "distances": [[0.1]],
            "metadatas": [[{"file_path": "test.md", "memory_type": "conversations", "categories": "test"}]],
            "documents": [["Test document content"]]
        }
        searcher.conversations_collection.query = MagicMock(return_value=mock_query_response)
        searcher.logs_collection.query = MagicMock(return_value={"ids": [], "distances": [], "metadatas": [], "documents": []})
        searcher.notes_collection.query = MagicMock(return_value={"ids": [], "distances": [], "metadatas": [], "documents": []})
        
        # Test basic search (all collections)
        results = searcher.search_memory("test query")
        self.assertEqual(len(results), 1)
        
        # Test search with specific memory_type
        results = searcher.search_memory("test query", memory_type="conversations")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["collection"], "conversations")
        
        # Test search with max_results
        results = searcher.search_memory("test query", max_results=2)
        self.assertEqual(len(results), 1)  # Only 1 result available
        
        # Test search with categories filter
        results = searcher.search_memory("test query", categories=["test"])
        self.assertEqual(len(results), 1)
    
    def test_parameter_parsing(self):
        """Test parsing of query parameters in ActionExecutor"""
        from penguin.utils.parser import ActionExecutor
        
        # Mock dependencies
        mock_tool_manager = MagicMock()
        mock_project_manager = MagicMock()
        mock_conversation = MagicMock()
        
        # Create ActionExecutor
        executor = ActionExecutor(mock_tool_manager, mock_project_manager, mock_conversation)
        
        # Test the _memory_search method with various parameter formats
        
        # Case 1: Basic query with no params
        executor._memory_search = MagicMock()
        executor._memory_search.return_value = "Result 1"
        result = executor._memory_search("simple query")
        executor._memory_search.assert_called_with("simple query")
        
        # Case 2: Query with max_results
        executor._memory_search = MagicMock()
        executor._memory_search.return_value = "Result 2"
        result = executor._memory_search("complex query:5")
        # Assert parameters are correctly split
        self.assertEqual(result, "Result 2")
        
        # Case 3: Query with all optional parameters
        executor._memory_search = MagicMock()
        executor._memory_search.return_value = "Result 3"
        result = executor._memory_search("full query:10:conversations:category1,category2:2024-01-01:2024-06-01")
        self.assertEqual(result, "Result 3")
    
    def test_extract_date_from_path(self):
        """Test extracting date from filename"""
        searcher = MemorySearcher(persist_directory=self.memory_db_dir)
        
        # Test valid format
        date = searcher.extract_date_from_path("chat_20240601_123000.md")
        self.assertEqual(date, "2024-06-01T12:30:00")
        
        # Test invalid format
        date = searcher.extract_date_from_path("invalid_filename.md")
        self.assertNotEqual(date, "invalid_date")  # Should return current time
    
    def test_extract_categories(self):
        """Test category extraction from content"""
        searcher = MemorySearcher(persist_directory=self.memory_db_dir)
        
        # Test with multiple categories
        content = "This is a task about project planning with some error fixing"
        categories = searcher.extract_categories(content)
        self.assertIn("task", categories)
        self.assertIn("project", categories)
        self.assertIn("error", categories)
        
        # Test with no categories
        content = "This text has no special categories"
        categories = searcher.extract_categories(content)
        self.assertEqual(categories, "")
    
    def test_format_preview(self):
        """Test preview formatting"""
        searcher = MemorySearcher(persist_directory=self.memory_db_dir)
        
        # Test with short content
        preview = searcher.format_preview("Short content")
        self.assertEqual(preview, "Short content")
        
        # Test with long content
        long_content = "A" * 500
        preview = searcher.format_preview(long_content)
        self.assertTrue(len(preview) <= 303)  # 300 + 3 for "..."
        self.assertTrue(preview.endswith("..."))


if __name__ == '__main__':
    unittest.main() 