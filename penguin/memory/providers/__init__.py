"""
Enhanced Memory Provider System

This package provides a flexible, interchangeable memory provider architecture
that supports multiple backends while maintaining a consistent interface.

Available Providers:
- SQLiteMemoryProvider: Lightweight, dependency-free provider using SQLite + FTS
- FileMemoryProvider: Simple file-based provider for basic functionality  
- FAISSMemoryProvider: High-performance vector search (requires faiss)
- ChromaMemoryProvider: ChromaDB integration (when dependencies available)
"""

from .base import MemoryProvider, MemoryProviderError
from .factory import MemoryProviderFactory

# Provider imports with graceful fallbacks
try:
    from .sqlite_provider import SQLiteMemoryProvider
except ImportError:
    SQLiteMemoryProvider = None

try:
    from .file_provider import FileMemoryProvider
except ImportError:
    FileMemoryProvider = None

try:
    from .faiss_provider import FAISSMemoryProvider
except ImportError:
    FAISSMemoryProvider = None

# Avoid importing Chroma provider at import-time; it will be loaded by factory if deps exist
ChromaMemoryProvider = None

__all__ = [
    'MemoryProvider',
    'MemoryProviderError', 
    'MemoryProviderFactory',
    'SQLiteMemoryProvider',
    'FileMemoryProvider',
    'FAISSMemoryProvider',
    'ChromaMemoryProvider'
] 