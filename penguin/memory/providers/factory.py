"""
Memory Provider Factory

Automatically detects available providers and creates instances based on
configuration and dependency availability.
"""

import logging
from typing import Any, Dict, Optional, Type, List
from pathlib import Path
from penguin.config import WORKSPACE_PATH  # Ensures consistent workspace reference

from .base import MemoryProvider, MemoryProviderError

logger = logging.getLogger(__name__)


class MemoryProviderFactory:
    """
    Factory for creating memory providers with automatic detection
    of available dependencies and optimal provider selection.
    """
    
    # Provider registry - populated dynamically based on available imports
    _providers: Dict[str, Type[MemoryProvider]] = {}
    _provider_priorities = ['lancedb', 'faiss', 'sqlite', 'file']  # Preferred order
    
    @classmethod
    def register_provider(cls, name: str, provider_class: Type[MemoryProvider]):
        """Register a provider class with the factory."""
        cls._providers[name] = provider_class
        logger.debug(f"Registered memory provider: {name}")
    
    @classmethod
    def get_available_providers(cls) -> List[str]:
        """Get list of available provider names."""
        # Ensure providers are loaded
        cls._load_available_providers()
        return list(cls._providers.keys())
    
    @classmethod
    def create_provider(cls, config: Dict[str, Any]) -> MemoryProvider:
        """
        Create a memory provider based on configuration and available dependencies.
        
        Args:
            config: Configuration dictionary containing provider settings
            
        Returns:
            Initialized memory provider instance
            
        Raises:
            MemoryProviderError: If no suitable provider can be created
        """
        # Ensure providers are loaded
        cls._load_available_providers()
        
        provider_type = config.get("provider", "auto")
        
        # Debug logging to track provider selection
        logger.info(f"Memory provider config: {config}")
        logger.info(f"Requested provider type: {provider_type}")
        
        if provider_type == "auto":
            provider_type = cls._detect_best_provider()
            logger.info(f"Auto-detected best provider: {provider_type}")
        else:
            logger.info(f"Using configured provider: {provider_type}")
        
        if provider_type not in cls._providers:
            available = ', '.join(cls._providers.keys())
            raise MemoryProviderError(
                f"Provider '{provider_type}' not available. "
                f"Available providers: {available}"
            )
        
        try:
            provider_class = cls._providers[provider_type]
            provider_config = cls._prepare_provider_config(config, provider_type)
            
            logger.info(f"Creating {provider_type} memory provider")
            return provider_class(provider_config)
            
        except Exception as e:
            raise MemoryProviderError(f"Failed to create {provider_type} provider: {str(e)}")
    
    @classmethod
    def _detect_best_provider(cls) -> str:
        """
        Detect the best available provider based on dependencies and performance.
        
        Returns:
            Name of the best available provider
        """
        for provider_name in cls._provider_priorities:
            if provider_name in cls._providers:
                dependency_check = cls._check_provider_dependencies(provider_name)
                if dependency_check['available']:
                    logger.debug(f"Selected {provider_name} provider: {dependency_check['reason']}")
                    return provider_name
                else:
                    logger.debug(f"Skipping {provider_name} provider: {dependency_check['reason']}")
        
        # Fallback to any available provider
        if cls._providers:
            fallback = list(cls._providers.keys())[0]
            logger.warning(f"Using fallback provider: {fallback}")
            return fallback
        
        raise MemoryProviderError("No memory providers available")
    
    @classmethod
    def _check_provider_dependencies(cls, provider_name: str) -> Dict[str, Any]:
        """
        Check if dependencies for a provider are available.
        
        Args:
            provider_name: Name of the provider to check
            
        Returns:
            Dictionary with 'available' boolean and 'reason' string
        """
        if provider_name == 'lancedb':
            try:
                import lancedb  # noqa: F401
                import pyarrow  # noqa: F401
                return {'available': True, 'reason': 'LanceDB and PyArrow available'}
            except ImportError as e:
                return {'available': False, 'reason': f'LanceDB dependencies missing: {str(e)}'}
        
        elif provider_name == 'faiss':
            try:
                import faiss  # noqa: F401
                import numpy  # noqa: F401
                return {'available': True, 'reason': 'FAISS and numpy available'}
            except ImportError as e:
                return {'available': False, 'reason': f'FAISS dependencies missing: {str(e)}'}
        
        elif provider_name == 'chroma':
            try:
                import chromadb  # noqa: F401
                import sentence_transformers  # noqa: F401
                return {'available': True, 'reason': 'ChromaDB and sentence-transformers available'}
            except ImportError as e:
                return {'available': False, 'reason': f'ChromaDB dependencies missing: {str(e)}'}
        
        elif provider_name == 'sqlite':
            try:
                import sqlite3  # noqa: F401
                # Numpy is an optional dependency for vector search
                return {'available': True, 'reason': 'SQLite available (built-in)'}
            except ImportError as e:
                return {'available': False, 'reason': f'SQLite not available: {str(e)}'}
        
        elif provider_name == 'file':
            try:
                # Numpy is an optional dependency for vector search
                import numpy # noqa: F401
                return {'available': True, 'reason': 'File provider available'}
            except ImportError as e:
                return {'available': False, 'reason': f'Numpy not installed, which is required for vector search.'}
        
        else:
            return {'available': False, 'reason': f'Unknown provider: {provider_name}'}
    
    @classmethod
    def _prepare_provider_config(cls, global_config: Dict[str, Any], provider_type: str) -> Dict[str, Any]:
        """
        Prepare provider-specific configuration from global config.
        
        Args:
            global_config: Global memory configuration
            provider_type: Type of provider being created
            
        Returns:
            Provider-specific configuration dictionary
        """
        # Start with global settings
        provider_config = {
            'provider_type': provider_type,
            'embedding_model': global_config.get('embedding_model', 'sentence-transformers/all-MiniLM-L6-v2'),
            # Resolve storage path; prefer explicit config, else default to workspace
            # directory. This prevents accidental creation of 'memory_db' inside the
            # repository when users forget to specify a path.
            'storage_path': global_config.get('storage_path', str(Path(WORKSPACE_PATH) / 'memory_db'))
        }
        
        # Add provider-specific settings
        providers_config = global_config.get('providers', {})
        if provider_type in providers_config:
            provider_config.update(providers_config[provider_type])
        
        return provider_config
    
    @classmethod
    def _load_available_providers(cls):
        """Load all available providers based on installed dependencies."""
        if cls._providers:
            return  # Already loaded
        
        # Try to import and register each provider
        
        # LanceDB Provider (high performance, preferred)
        try:
            from .lance_provider import LanceMemoryProvider
            cls.register_provider('lancedb', LanceMemoryProvider)
        except ImportError as e:
            logger.debug(f"LanceDB provider not available: {e}")
        
        # SQLite Provider (always available)
        try:
            from .sqlite_provider import SQLiteMemoryProvider
            cls.register_provider('sqlite', SQLiteMemoryProvider)
        except ImportError as e:
            logger.warning(f"SQLite provider not available: {e}")
        
        # File Provider (always available)
        try:
            from .file_provider import FileMemoryProvider
            cls.register_provider('file', FileMemoryProvider)
        except ImportError as e:
            logger.warning(f"File provider not available: {e}")
        
        # FAISS Provider (optional)
        try:
            from .faiss_provider import FAISSMemoryProvider
            cls.register_provider('faiss', FAISSMemoryProvider)
        except ImportError as e:
            logger.debug(f"FAISS provider not available: {e}")
        
        # ChromaDB Provider (optional, may have conflicts)
        try:
            from .chroma_provider import ChromaMemoryProvider
            cls.register_provider('chroma', ChromaMemoryProvider)
        except ImportError as e:
            logger.debug(f"ChromaDB provider not available: {e}")
        
        if not cls._providers:
            raise MemoryProviderError("No memory providers could be loaded")
        
        logger.info(f"Loaded memory providers: {', '.join(cls._providers.keys())}")
    
    @classmethod
    def get_provider_info(cls, provider_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get information about providers.
        
        Args:
            provider_name: Specific provider to get info for, or None for all
            
        Returns:
            Dictionary with provider information
        """
        cls._load_available_providers()
        
        if provider_name:
            if provider_name not in cls._providers:
                raise MemoryProviderError(f"Provider '{provider_name}' not available")
            
            dependency_check = cls._check_provider_dependencies(provider_name)
            return {
                'name': provider_name,
                'class': cls._providers[provider_name].__name__,
                'available': dependency_check['available'],
                'reason': dependency_check['reason']
            }
        else:
            # Return info for all providers
            info = {}
            for name in cls._providers:
                dependency_check = cls._check_provider_dependencies(name)
                info[name] = {
                    'class': cls._providers[name].__name__,
                    'available': dependency_check['available'],
                    'reason': dependency_check['reason']
                }
            return info
    
    @classmethod
    def health_check_all_providers(cls) -> Dict[str, Any]:
        """
        Perform health check on all available providers.
        
        Returns:
            Dictionary with health status for each provider
        """
        cls._load_available_providers()
        
        health_status = {
            'overall_status': 'healthy',
            'providers': {},
            'recommendations': []
        }
        
        healthy_count = 0
        
        for provider_name in cls._providers:
            dependency_check = cls._check_provider_dependencies(provider_name)
            
            if dependency_check['available']:
                health_status['providers'][provider_name] = {
                    'status': 'available',
                    'dependencies': 'OK',
                    'reason': dependency_check['reason']
                }
                healthy_count += 1
            else:
                health_status['providers'][provider_name] = {
                    'status': 'unavailable',
                    'dependencies': 'MISSING',
                    'reason': dependency_check['reason']
                }
        
        # Overall status assessment
        if healthy_count == 0:
            health_status['overall_status'] = 'critical'
            health_status['recommendations'].append("No memory providers available")
        elif healthy_count == 1:
            health_status['overall_status'] = 'degraded'
            health_status['recommendations'].append("Only one provider available - consider installing additional options")
        
        # Specific recommendations
        if 'lancedb' not in health_status['providers'] or health_status['providers']['lancedb']['status'] == 'unavailable':
            health_status['recommendations'].append("Install LanceDB for high-performance vector search: pip install lancedb")
        
        if 'faiss' not in health_status['providers'] or health_status['providers']['faiss']['status'] == 'unavailable':
            health_status['recommendations'].append("Install FAISS for high-performance vector search: pip install faiss-cpu")
        
        if 'sqlite' not in health_status['providers'] or health_status['providers']['sqlite']['status'] == 'unavailable':
            health_status['recommendations'].append("SQLite should be available by default - check Python installation")
        
        return health_status


# Convenience function for easy provider creation
def create_memory_provider(config: Dict[str, Any]) -> MemoryProvider:
    """
    Convenience function to create a memory provider.
    
    Args:
        config: Memory configuration dictionary
        
    Returns:
        Initialized memory provider
    """
    return MemoryProviderFactory.create_provider(config) 