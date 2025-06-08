# LanceDB Memory Provider

The LanceDB Memory Provider is a high-performance vector database implementation for Penguin's memory system. It leverages LanceDB's columnar storage format and built-in embedding capabilities to provide fast vector similarity search with excellent storage efficiency.

## Features

### Core Capabilities
- **Vector Similarity Search**: Fast semantic search using embeddings
- **Hybrid Search**: Combines vector and full-text search for better results
- **Automatic Indexing**: Creates vector indexes automatically for improved performance
- **Multiple Embedding Models**: Support for various embedding providers
- **Metadata Filtering**: Advanced filtering capabilities on memory attributes
- **Backup/Restore**: Built-in data backup and restoration functionality

### Performance Benefits
- **Columnar Storage**: Efficient storage using Lance format
- **Automatic Optimization**: Self-optimizing indexes and query plans
- **Memory Efficiency**: Low memory footprint for large datasets
- **Fast Queries**: Sub-second search even with millions of records

## Installation

### Prerequisites
```bash
# Install LanceDB and dependencies
pip install -r requirements_lancedb.txt
```

### Required Dependencies
- `lancedb>=0.3.0` - Core LanceDB package
- `pyarrow>=10.0.0` - Arrow format support
- `pandas>=1.5.0` - Data manipulation
- `sentence-transformers>=2.2.0` - Local embeddings (optional)

## Configuration

### Basic Configuration
```yaml
memory:
  provider: "lancedb"
  config:
    storage_path: "./memory_db"
    embedding_model: "sentence-transformers/all-MiniLM-L6-v2"
    table_name: "memory_records"
```

### Advanced Configuration
```yaml
memory:
  provider: "lancedb"
  config:
    storage_path: "./memory_db"
    embedding_model: "openai"  # or "cohere", "sentence-transformers/..."
    table_name: "memory_records"
    
    # OpenAI embedding configuration (if using OpenAI)
    openai_api_key: "your-api-key"
    openai_model: "text-embedding-ada-002"
    
    # Performance tuning
    auto_index_threshold: 100  # Create index after N records
    batch_size: 1000          # Batch size for bulk operations
```

## Usage Examples

### Basic Operations

```python
from penguin.memory.providers.lance_provider import LanceMemoryProvider

# Initialize provider
config = {
    "storage_path": "./memory_db",
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
    "table_name": "my_memories"
}

provider = LanceMemoryProvider(config)
await provider._initialize_provider()

# Add a memory
memory_id = await provider.add_memory(
    content="Python is a versatile programming language",
    metadata={"type": "knowledge", "source": "documentation"},
    categories=["programming", "python"]
)

# Search memories
results = await provider.search_memory(
    query="programming language",
    max_results=5
)

# Get specific memory
memory = await provider.get_memory(memory_id)

# Update memory
await provider.update_memory(
    memory_id,
    content="Python is a powerful and versatile programming language",
    metadata={"type": "knowledge", "source": "updated"}
)

# Delete memory
await provider.delete_memory(memory_id)
```

### Advanced Search

```python
# Filtered search
results = await provider.search_memory(
    query="machine learning",
    max_results=10,
    filters={
        "memory_type": "knowledge",
        "categories": ["ai", "ml"],
        "date_after": "2024-01-01",
        "source": "research"
    }
)

# Hybrid search (vector + text)
hybrid_results = await provider.hybrid_search(
    query="neural networks deep learning",
    max_results=5,
    vector_weight=0.7,
    text_weight=0.3
)
```

### Backup and Restore

```python
# Backup memories
await provider.backup_memories("./backup/memories_2024.parquet")

# Restore from backup
await provider.restore_memories("./backup/memories_2024.parquet")
```

## Embedding Models

### Local Models (Sentence Transformers)
```python
# Fast, lightweight model
"sentence-transformers/all-MiniLM-L6-v2"

# Better quality, larger model
"sentence-transformers/all-mpnet-base-v2"

# Multilingual support
"sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
```

### Cloud Models
```python
# OpenAI embeddings
config = {
    "embedding_model": "openai",
    "openai_api_key": "your-key",
    "openai_model": "text-embedding-ada-002"
}

# Cohere embeddings
config = {
    "embedding_model": "cohere",
    "cohere_api_key": "your-key",
    "cohere_model": "embed-english-v2.0"
}
```

## Performance Tuning

### Indexing Strategy
```python
# Automatic indexing (recommended)
config = {
    "auto_index_threshold": 100,  # Create index after 100 records
    "index_type": "ivf_pq"       # Index type for large datasets
}

# Manual index creation
await provider._create_index()
```

### Memory Optimization
```python
# Batch operations for better performance
memories = [
    {"content": "...", "metadata": {...}, "categories": [...]},
    # ... more memories
]

# Add in batches
for batch in chunks(memories, batch_size=100):
    for memory in batch:
        await provider.add_memory(**memory)
```

### Query Optimization
```python
# Use specific filters to reduce search space
results = await provider.search_memory(
    query="search term",
    max_results=10,
    filters={
        "memory_type": "specific_type",  # Reduces search space
        "date_after": "2024-01-01"      # Time-based filtering
    }
)
```

## Monitoring and Diagnostics

### Health Check
```python
health = await provider.health_check()
print(f"Status: {health['status']}")
print(f"Checks: {health['checks']}")
```

### Statistics
```python
stats = await provider.get_memory_stats()
print(f"Total memories: {stats['total_memories']}")
print(f"Search count: {stats['search_count']}")
print(f"Storage path: {stats['storage_path']}")
```

### Performance Monitoring
```python
# Monitor search performance
import time

start_time = time.time()
results = await provider.search_memory("query")
search_time = time.time() - start_time

print(f"Search took {search_time:.3f}s for {len(results)} results")
```

## Troubleshooting

### Common Issues

#### 1. Import Errors
```bash
# Install missing dependencies
pip install lancedb pyarrow pandas

# For embedding models
pip install sentence-transformers  # Local embeddings
pip install openai                 # OpenAI embeddings
```

#### 2. Performance Issues
```python
# Check if index exists
stats = await provider.get_memory_stats()
if not stats.get('index_created'):
    await provider._create_index()

# Reduce embedding model size
config['embedding_model'] = "sentence-transformers/all-MiniLM-L6-v2"
```

#### 3. Storage Issues
```python
# Check storage path permissions
import os
storage_path = config['storage_path']
if not os.access(storage_path, os.W_OK):
    print(f"No write permission to {storage_path}")

# Check disk space
import shutil
free_space = shutil.disk_usage(storage_path).free
print(f"Free space: {free_space / (1024**3):.1f} GB")
```

### Error Handling
```python
try:
    results = await provider.search_memory("query")
except Exception as e:
    logger.error(f"Search failed: {e}")
    
    # Check provider health
    health = await provider.health_check()
    if health['status'] != 'healthy':
        logger.error(f"Provider unhealthy: {health}")
```

## Testing

### Run Tests
```bash
# Run comprehensive tests
python run_lance_tests.py

# Run specific test
python -m pytest test_lance_provider.py::TestLanceMemoryProvider::test_add_memory
```

### Performance Benchmarks
```bash
# Run performance benchmarks
python run_lance_tests.py --benchmark-only
```

## Migration

### From Other Providers
```python
# Export from old provider
old_memories = await old_provider.search_memory("", max_results=10000)

# Import to LanceDB
for memory in old_memories:
    await lance_provider.add_memory(
        memory['content'],
        memory['metadata'],
        memory.get('categories', [])
    )
```

### Backup Strategy
```python
# Regular backups
import schedule
import asyncio

async def backup_memories():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"./backups/memories_{timestamp}.parquet"
    await provider.backup_memories(backup_path)

# Schedule daily backups
schedule.every().day.at("02:00").do(lambda: asyncio.run(backup_memories()))
```

## Best Practices

### 1. Configuration
- Use local embedding models for privacy and speed
- Set appropriate `auto_index_threshold` based on dataset size
- Configure proper storage path with sufficient disk space

### 2. Data Management
- Use meaningful categories and metadata for better filtering
- Implement regular backup schedules
- Monitor storage usage and performance metrics

### 3. Performance
- Create indexes for large datasets (>1000 records)
- Use batch operations for bulk data loading
- Implement proper error handling and retry logic

### 4. Security
- Store API keys securely (environment variables)
- Implement proper access controls for storage directory
- Regular security updates for dependencies

## API Reference

See the full API documentation in the provider source code for detailed method signatures and parameters.

## Support

For issues and questions:
1. Check the troubleshooting section above
2. Run the health check and diagnostics
3. Review the test suite for usage examples
4. Check LanceDB documentation for advanced features 