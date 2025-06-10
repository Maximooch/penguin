"""Embedding helper for Penguin memory system.

Centralised utility to lazily load / cache sentence-transformers models so that
all providers share a single model instance per process.  Keeping it here
avoids each provider importing torch / model weights on its own and reduces
GPU / CPU RAM usage.
"""
from functools import lru_cache
from typing import Callable, List, Optional

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "sentence-transformers package is required for embedding support. "
        "Install via `pip install sentence-transformers` or use a provider that "
        "does not rely on embeddings."
    ) from e


@lru_cache(maxsize=4)
def get_embedder(model_name: str = "sentence-transformers/all-MiniLM-L6-v2", device: Optional[str] = None) -> Callable[[List[str]], List[List[float]]]:
    """Return a thread-safe encode function for *model_name*.

    The returned callable maps a list of strings to a list of float vectors.
    Subsequent calls with the same *model_name*/*device* pair reuse the same
    underlying `SentenceTransformer` object (cached in process memory).
    If device is None, it will automatically use the best available device.
    """
    model = SentenceTransformer(model_name, device=device)
    return model.encode 