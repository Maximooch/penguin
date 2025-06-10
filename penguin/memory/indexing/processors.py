"""
Content-Aware Processors for the Indexing System

Defines a pluggable architecture for processing different file types. Each
processor is responsible for extracting content and relevant metadata from a
file, which can then be used for embedding and indexing.
"""

import ast
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from penguin.tools.core.ast_analyzer import ASTAnalyzer

logger = logging.getLogger(__name__)


class ContentProcessor(ABC):
    """
    Abstract base class for content processors.

    Subclasses should implement the logic to handle a specific file type,
    extracting its content and any relevant structured metadata.
    """

    @abstractmethod
    def can_process(self, file_path: str) -> bool:
        """
        Check if this processor can handle the given file type.

        Args:
            file_path: The path to the file.

        Returns:
            True if the processor can handle the file, False otherwise.
        """
        pass

    @abstractmethod
    async def process(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Process the file to extract content and metadata.

        Args:
            file_path: The path to the file.

        Returns:
            A dictionary containing the extracted 'content' and 'metadata',
            or None if processing fails.
        """
        pass


class PythonCodeProcessor(ContentProcessor):
    """
    Processes Python source code files using a detailed AST analyzer.
    """

    def __init__(self):
        self.analyzer = ASTAnalyzer()

    def can_process(self, file_path: str) -> bool:
        return file_path.endswith('.py')

    async def process(self, file_path: str) -> Optional[Dict[str, Any]]:
        try:
            # The analyzer reads the file itself.
            analysis_result = self.analyzer.analyze_file(file_path)

            if not analysis_result:
                # If analysis fails (e.g., syntax error), index the raw content.
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return {
                    'content': content,
                    'metadata': {
                        'file_type': 'python',
                        'path': file_path,
                        'has_syntax_error': True,
                    }
                }

            # For successful analysis, we can use the full content from the file
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            return {
                'content': content,
                'metadata': {
                    'file_type': 'python',
                    'path': file_path,
                    **analysis_result,
                }
            }
        except Exception as e:
            logger.error(f"Error processing Python file {file_path}: {e}")
            return None


class MarkdownProcessor(ContentProcessor):
    """
    Processes Markdown documentation files.

    Extracts the file's text content and parses out headers as metadata.
    """

    def can_process(self, file_path: str) -> bool:
        return file_path.endswith(('.md', '.markdown'))

    async def process(self, file_path: str) -> Optional[Dict[str, Any]]:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            headers = self._extract_headers(content)
            
            return {
                'content': content,
                'metadata': {
                    'file_type': 'markdown',
                    'path': file_path,
                    'headers': headers,
                }
            }
        except Exception as e:
            logger.error(f"Error processing Markdown file {file_path}: {e}")
            return None

    def _extract_headers(self, content: str) -> List[str]:
        """Extract all markdown headers from the content."""
        headers = []
        for line in content.splitlines():
            if line.strip().startswith('#'):
                headers.append(line.strip().lstrip('#').strip())
        return headers


class GenericTextProcessor(ContentProcessor):
    """
    A fallback processor for any generic text file.
    """

    def can_process(self, file_path: str) -> bool:
        # This processor can handle any file, but should have the lowest priority.
        # It's better to rely on more specific processors first.
        return True

    async def process(self, file_path: str) -> Optional[Dict[str, Any]]:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return {
                'content': content,
                'metadata': {
                    'file_type': 'text',
                    'path': file_path,
                }
            }
        except (UnicodeDecodeError, IOError):
            # This is likely a binary file, skip it.
            return None
        except Exception as e:
            logger.error(f"Error processing generic text file {file_path}: {e}")
            return None 