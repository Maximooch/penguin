"""
Enhanced Memory System for Penguin

This package provides a flexible, interchangeable memory provider architecture
that supports multiple backends while maintaining a consistent interface.

Key Features:
- Multiple provider options (SQLite, File, FAISS, ChromaDB)
- Automatic provider detection and selection
- Comprehensive search capabilities
- Backup and restore functionality
- Migration utilities for legacy data
- Health monitoring and diagnostics

Quick Start:
    from penguin.memory import create_memory_provider
    
    config = {'provider': 'auto', 'storage_path': './memory_db'}
    provider = create_memory_provider(config)
    await provider.initialize()
    
    memory_id = await provider.add_memory("Hello, world!")
    results = await provider.search_memory("hello")
"""

# Core provider system
from .providers.base import MemoryProvider, MemoryProviderError, MemoryTool
from .providers.factory import MemoryProviderFactory, create_memory_provider

# Individual providers (graceful imports)
try:
    from .providers.sqlite_provider import SQLiteMemoryProvider
except ImportError:
    SQLiteMemoryProvider = None

try:
    from .providers.file_provider import FileMemoryProvider
except ImportError:
    FileMemoryProvider = None

try:
    from .providers.faiss_provider import FAISSMemoryProvider
except ImportError:
    FAISSMemoryProvider = None

# Migration utilities
from .migration import MemoryMigration, migrate_memory_system

# Legacy compatibility - maintain existing interfaces
from .summary_notes import SummaryNotes
from .declarative_memory import DeclarativeMemory

# Try to import legacy provider for migration
try:
    from .chroma_provider import ChromaProvider
except ImportError:
    ChromaProvider = None

# Legacy provider interface for backward compatibility
try:
    from .provider import MemoryProvider as LegacyMemoryProvider
    from .provider import MemoryTool as LegacyMemoryTool
except ImportError:
    LegacyMemoryProvider = None
    LegacyMemoryTool = None

# AFTER the existing imports at the top of the file but before other code runs - inject workspace-aware default path
from pathlib import Path
from penguin.config import WORKSPACE_PATH  # Provides the resolved workspace directory

# Workspace-aware default location for all memory provider data. This keeps the project
# repository clean and ensures memory data lives alongside the rest of the runtime
# workspace artefacts (conversations/, logs/, etc.)
DEFAULT_STORAGE_PATH = Path(WORKSPACE_PATH) / "memory_db"
# Ensure the directory exists early to avoid surprises later. This is a no-op if it is
# already present.
DEFAULT_STORAGE_PATH.mkdir(parents=True, exist_ok=True)

__all__ = [
    # New provider system
    'MemoryProvider',
    'MemoryProviderError',
    'MemoryTool',
    'MemoryProviderFactory',
    'create_memory_provider',
    
    # Individual providers
    'SQLiteMemoryProvider',
    'FileMemoryProvider', 
    'FAISSMemoryProvider',
    
    # Migration
    'MemoryMigration',
    'migrate_memory_system',
    
    # Legacy compatibility
    'SummaryNotes',
    'DeclarativeMemory',
    'ChromaProvider',
    'LegacyMemoryProvider',
    'LegacyMemoryTool',
]


def get_memory_system_info():
    """Get information about the memory system."""
    return {
        'available_providers': MemoryProviderFactory.get_available_providers(),
        'provider_info': MemoryProviderFactory.get_provider_info(),
        'health_status': MemoryProviderFactory.health_check_all_providers(),
        'version': '2.0.0',
        'features': [
            'Multiple provider backends',
            'Automatic provider selection',
            'Full-text search',
            'Metadata filtering',
            'Backup and restore',
            'Health monitoring',
            'Migration utilities'
        ]
    }


# Convenience function for quick setup
async def create_memory_system(config=None):
    """
    Create and initialize a memory system with sensible defaults.
    
    Args:
        config: Optional configuration dict. If None, uses auto-detection.
        
    Returns:
        Initialized MemoryTool instance ready for use
    """
    if config is None:
        # Fall back to a workspace-relative storage path instead of a path inside the
        # repository. Users may still override this by passing an explicit config.
        config = {
            'provider': 'auto',
            'storage_path': str(DEFAULT_STORAGE_PATH)
        }
    else:
        # Ensure a storage_path key exists; if not, provide the workspace default.
        config.setdefault('storage_path', str(DEFAULT_STORAGE_PATH))
    
    provider = create_memory_provider(config)
    await provider.initialize()
    
    return MemoryTool(provider) 