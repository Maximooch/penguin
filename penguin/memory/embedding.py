"""Embedding helper for Penguin memory system.

Centralised utility to lazily load / cache sentence-transformers models so that
all providers share a single model instance per process.  Keeping it here
avoids each provider importing torch / model weights on its own and reduces
GPU / CPU RAM usage.

NOTE: The sentence_transformers import is deferred to first use of get_embedder()
to avoid ~1 second import overhead at startup.
"""
from functools import lru_cache
from typing import Callable, List, Optional, TYPE_CHECKING

# Type hint only - actual import deferred to get_embedder()
if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer  # type: ignore

# Lazy import cache
_SentenceTransformer = None


def _ensure_sentence_transformers():
    """Lazy import sentence_transformers on first use."""
    global _SentenceTransformer
    if _SentenceTransformer is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            _SentenceTransformer = SentenceTransformer
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "sentence-transformers package is required for embedding support. "
                "Install via `pip install sentence-transformers` or use a provider that "
                "does not rely on embeddings."
            ) from e
    return _SentenceTransformer


@lru_cache(maxsize=4)
def get_embedder(model_name: str = "sentence-transformers/all-MiniLM-L6-v2", device: Optional[str] = None) -> Callable[[List[str]], List[List[float]]]:
    """Return a thread-safe encode function for *model_name*.

    The returned callable maps a list of strings to a list of float vectors.
    Subsequent calls with the same *model_name*/*device* pair reuse the same
    underlying `SentenceTransformer` object (cached in process memory).
    If device is None, it will automatically use the best available device.
    """
    SentenceTransformer = _ensure_sentence_transformers()
    model = SentenceTransformer(model_name, device=device)
    return model.encode 