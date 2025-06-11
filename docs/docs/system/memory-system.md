---
sidebar_position: 4
---

# Memory System

Penguin's memory system stores and retrieves knowledge across sessions. It is built around a pluggable provider architecture so you can choose the backend that best fits your environment.

## Overview

The `penguin.memory` package exposes a `MemoryProvider` interface and a `MemoryProviderFactory` that selects the best available provider. Providers implement features like full‑text search and vector embeddings for semantic queries. Supported providers include:

- **SQLite** – lightweight database using FTS5 and optional embeddings.
- **File** – simple JSONL storage with in-memory vector search.
- **FAISS** – high-performance vector search.
- **LanceDB** – advanced vector database with hybrid search.
- **ChromaDB** – optional vector store for legacy compatibility.

If the configuration sets `provider: auto`, the factory attempts to use the best provider available on your system.

## Quick Start

```python
from penguin.memory import create_memory_system

memory = await create_memory_system()
mem_id = await memory.add_memory("Remember this text")
results = await memory.search_memory("remember")
```

## Configuration

Edit `config.yml` to select a provider and adjust settings:

```yaml
memory:
  provider: faiss  # or "auto", "sqlite", "file", "lance", "chroma"
  storage_path: "${paths.memory_db}"
  embedding_model: sentence-transformers/all-MiniLM-L6-v2
  providers:
    sqlite:
      database_file: penguin_memory.db
      enable_fts: true
    file:
      storage_dir: file_memory
      enable_embeddings: true
```

Each provider may define additional options as shown above.

## Backup and Restore

Every provider implements `backup_memories()` and `restore_memories()` for creating backups and restoring data. Use these methods to safeguard long-term knowledge.

