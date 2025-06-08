"""
Memory System Migration Utility

Helps migrate data from the old memory system to the new provider-based system.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .providers.base import MemoryProvider
from .providers.factory import MemoryProviderFactory

logger = logging.getLogger(__name__)


class MemoryMigration:
    """
    Utility for migrating memory data between different providers
    and from legacy memory systems.
    """
    
    def __init__(self, workspace_path: str = "./"):
        """
        Initialize migration utility.
        
        Args:
            workspace_path: Path to the Penguin workspace
        """
        self.workspace_path = Path(workspace_path)
        self.legacy_paths = {
            'chroma_db': self.workspace_path / 'chroma_db',
            'memory_db': self.workspace_path / 'memory_db',
            'conversations': self.workspace_path / 'conversations',
            'logs': self.workspace_path / 'logs'
        }
    
    async def migrate_to_new_system(
        self, 
        target_config: Dict[str, Any],
        backup_existing: bool = True
    ) -> Dict[str, Any]:
        """
        Migrate from legacy memory system to new provider-based system.
        
        Args:
            target_config: Configuration for the target memory provider
            backup_existing: Whether to backup existing data before migration
            
        Returns:
            Migration report dictionary
        """
        migration_report = {
            'start_time': datetime.now().isoformat(),
            'status': 'started',
            'legacy_data_found': {},
            'migrated_count': 0,
            'errors': [],
            'target_provider': target_config.get('provider', 'auto')
        }
        
        try:
            # Create target provider
            target_provider = MemoryProviderFactory.create_provider(target_config)
            await target_provider.initialize()
            
            # Backup existing data if requested
            if backup_existing:
                backup_result = await self._backup_legacy_data()
                migration_report['backup_result'] = backup_result
            
            # Discover legacy data sources
            legacy_data = await self._discover_legacy_data()
            migration_report['legacy_data_found'] = legacy_data
            
            # Migrate data from each source
            total_migrated = 0
            
            # Migrate from ChromaDB if present
            if legacy_data['chroma_memories'] > 0:
                try:
                    migrated = await self._migrate_from_chroma(target_provider)
                    total_migrated += migrated
                    logger.info(f"Migrated {migrated} memories from ChromaDB")
                except Exception as e:
                    error_msg = f"ChromaDB migration failed: {str(e)}"
                    migration_report['errors'].append(error_msg)
                    logger.error(error_msg)
            
            # Migrate from conversation logs
            if legacy_data['conversation_files'] > 0:
                try:
                    migrated = await self._migrate_from_conversations(target_provider)
                    total_migrated += migrated
                    logger.info(f"Migrated {migrated} memories from conversations")
                except Exception as e:
                    error_msg = f"Conversation migration failed: {str(e)}"
                    migration_report['errors'].append(error_msg)
                    logger.error(error_msg)
            
            # Migrate from log files
            if legacy_data['log_files'] > 0:
                try:
                    migrated = await self._migrate_from_logs(target_provider)
                    total_migrated += migrated
                    logger.info(f"Migrated {migrated} memories from logs")
                except Exception as e:
                    error_msg = f"Log migration failed: {str(e)}"
                    migration_report['errors'].append(error_msg)
                    logger.error(error_msg)
            
            migration_report['migrated_count'] = total_migrated
            migration_report['status'] = 'completed'
            migration_report['end_time'] = datetime.now().isoformat()
            
            await target_provider.close()
            
            logger.info(f"Migration completed. Migrated {total_migrated} memories.")
            
        except Exception as e:
            migration_report['status'] = 'failed'
            migration_report['error'] = str(e)
            migration_report['end_time'] = datetime.now().isoformat()
            logger.error(f"Migration failed: {str(e)}")
        
        return migration_report
    
    async def migrate_between_providers(
        self,
        source_config: Dict[str, Any],
        target_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Migrate data between two memory providers.
        
        Args:
            source_config: Configuration for source provider
            target_config: Configuration for target provider
            
        Returns:
            Migration report dictionary
        """
        migration_report = {
            'start_time': datetime.now().isoformat(),
            'status': 'started',
            'source_provider': source_config.get('provider', 'unknown'),
            'target_provider': target_config.get('provider', 'unknown'),
            'migrated_count': 0,
            'errors': []
        }
        
        source_provider = None
        target_provider = None
        
        try:
            # Initialize providers
            source_provider = MemoryProviderFactory.create_provider(source_config)
            target_provider = MemoryProviderFactory.create_provider(target_config)
            
            await source_provider.initialize()
            await target_provider.initialize()
            
            # Get all memories from source
            all_memories = await source_provider.list_memories(limit=10000)
            
            migrated_count = 0
            for memory_summary in all_memories:
                try:
                    # Get full memory data
                    memory_data = await source_provider.get_memory(memory_summary['id'])
                    if memory_data:
                        # Add to target provider
                        await target_provider.add_memory(
                            content=memory_data['content'],
                            metadata=memory_data.get('metadata', {}),
                            categories=memory_data.get('categories', [])
                        )
                        migrated_count += 1
                
                except Exception as e:
                    error_msg = f"Failed to migrate memory {memory_summary.get('id', 'unknown')}: {str(e)}"
                    migration_report['errors'].append(error_msg)
                    logger.warning(error_msg)
            
            migration_report['migrated_count'] = migrated_count
            migration_report['status'] = 'completed'
            migration_report['end_time'] = datetime.now().isoformat()
            
            logger.info(f"Provider migration completed. Migrated {migrated_count} memories.")
            
        except Exception as e:
            migration_report['status'] = 'failed'
            migration_report['error'] = str(e)
            migration_report['end_time'] = datetime.now().isoformat()
            logger.error(f"Provider migration failed: {str(e)}")
        
        finally:
            # Clean up providers
            if source_provider:
                await source_provider.close()
            if target_provider:
                await target_provider.close()
        
        return migration_report
    
    async def _discover_legacy_data(self) -> Dict[str, int]:
        """Discover legacy data sources and count entries."""
        legacy_data = {
            'chroma_memories': 0,
            'conversation_files': 0,
            'log_files': 0
        }
        
        try:
            # Check ChromaDB
            chroma_path = self.legacy_paths['chroma_db']
            if chroma_path.exists():
                # Try to count ChromaDB entries (this might fail due to conflicts)
                try:
                    import chromadb
                    client = chromadb.Client(chromadb.config.Settings(
                        persist_directory=str(chroma_path),
                        anonymized_telemetry=False
                    ))
                    collections = client.list_collections()
                    for collection in collections:
                        legacy_data['chroma_memories'] += collection.count()
                except Exception:
                    # If ChromaDB fails, estimate based on files
                    if (chroma_path / 'chroma.sqlite3').exists():
                        legacy_data['chroma_memories'] = 1  # At least some data
            
            # Check conversation files
            conversations_path = self.legacy_paths['conversations']
            if conversations_path.exists():
                legacy_data['conversation_files'] = len(list(conversations_path.glob('*.json')))
            
            # Check log files
            logs_path = self.legacy_paths['logs']
            if logs_path.exists():
                legacy_data['log_files'] = len(list(logs_path.glob('*.log')))
            
        except Exception as e:
            logger.warning(f"Error discovering legacy data: {str(e)}")
        
        return legacy_data
    
    async def _migrate_from_chroma(self, target_provider: MemoryProvider) -> int:
        """Migrate data from ChromaDB to target provider."""
        try:
            import chromadb
            
            chroma_path = self.legacy_paths['chroma_db']
            client = chromadb.Client(chromadb.config.Settings(
                persist_directory=str(chroma_path),
                anonymized_telemetry=False
            ))
            
            migrated_count = 0
            collections = client.list_collections()
            
            for collection in collections:
                # Get all documents from collection
                results = collection.get()
                
                if results and results['documents']:
                    for i, doc in enumerate(results['documents']):
                        metadata = results['metadatas'][i] if results['metadatas'] and i < len(results['metadatas']) else {}
                        
                        # Add to target provider
                        await target_provider.add_memory(
                            content=doc,
                            metadata=metadata,
                            categories=['migrated_from_chroma', collection.name]
                        )
                        migrated_count += 1
            
            return migrated_count
            
        except ImportError:
            logger.warning("ChromaDB not available for migration")
            return 0
        except Exception as e:
            logger.error(f"ChromaDB migration error: {str(e)}")
            return 0
    
    async def _migrate_from_conversations(self, target_provider: MemoryProvider) -> int:
        """Migrate data from conversation files to target provider."""
        migrated_count = 0
        conversations_path = self.legacy_paths['conversations']
        
        try:
            for conv_file in conversations_path.glob('*.json'):
                with open(conv_file, 'r', encoding='utf-8') as f:
                    conversation_data = json.load(f)
                
                # Extract meaningful content from conversation
                if isinstance(conversation_data, dict):
                    messages = conversation_data.get('messages', [])
                    for message in messages:
                        if isinstance(message, dict) and 'content' in message:
                            content = message['content']
                            if content and len(content.strip()) > 10:  # Skip very short messages
                                metadata = {
                                    'source': 'conversation',
                                    'file': conv_file.name,
                                    'role': message.get('role', 'unknown'),
                                    'timestamp': message.get('timestamp', '')
                                }
                                
                                await target_provider.add_memory(
                                    content=content,
                                    metadata=metadata,
                                    categories=['migrated_from_conversation']
                                )
                                migrated_count += 1
        
        except Exception as e:
            logger.error(f"Conversation migration error: {str(e)}")
        
        return migrated_count
    
    async def _migrate_from_logs(self, target_provider: MemoryProvider) -> int:
        """Migrate data from log files to target provider."""
        migrated_count = 0
        logs_path = self.legacy_paths['logs']
        
        try:
            for log_file in logs_path.glob('*.log'):
                with open(log_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Only migrate non-empty, meaningful log content
                if content and len(content.strip()) > 50:
                    metadata = {
                        'source': 'log_file',
                        'file': log_file.name,
                        'migrated_at': datetime.now().isoformat()
                    }
                    
                    await target_provider.add_memory(
                        content=content,
                        metadata=metadata,
                        categories=['migrated_from_logs']
                    )
                    migrated_count += 1
        
        except Exception as e:
            logger.error(f"Log migration error: {str(e)}")
        
        return migrated_count
    
    async def _backup_legacy_data(self) -> Dict[str, Any]:
        """Create backup of legacy data before migration."""
        backup_result = {
            'timestamp': datetime.now().isoformat(),
            'backup_path': None,
            'backed_up_paths': [],
            'errors': []
        }
        
        try:
            backup_dir = self.workspace_path / 'memory_migration_backup' / datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_result['backup_path'] = str(backup_dir)
            
            # Backup each legacy path that exists
            for name, path in self.legacy_paths.items():
                if path.exists():
                    try:
                        import shutil
                        backup_target = backup_dir / name
                        if path.is_dir():
                            shutil.copytree(path, backup_target)
                        else:
                            shutil.copy2(path, backup_target)
                        backup_result['backed_up_paths'].append(str(path))
                    except Exception as e:
                        error_msg = f"Failed to backup {path}: {str(e)}"
                        backup_result['errors'].append(error_msg)
                        logger.warning(error_msg)
        
        except Exception as e:
            backup_result['errors'].append(f"Backup failed: {str(e)}")
            logger.error(f"Backup failed: {str(e)}")
        
        return backup_result


# Convenience function for migration
async def migrate_memory_system(
    workspace_path: str,
    target_config: Dict[str, Any],
    backup_existing: bool = True
) -> Dict[str, Any]:
    """
    Convenience function to migrate memory system.
    
    Args:
        workspace_path: Path to Penguin workspace
        target_config: Configuration for target memory provider
        backup_existing: Whether to backup existing data
        
    Returns:
        Migration report
    """
    migration = MemoryMigration(workspace_path)
    return await migration.migrate_to_new_system(target_config, backup_existing) 