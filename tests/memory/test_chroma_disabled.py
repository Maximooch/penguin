"""Keep the unsupported ChromaDB backend out of automatic memory selection."""

import pytest

from penguin.memory.providers.base import MemoryProviderError
from penguin.memory.providers.factory import MemoryProviderFactory


def test_chroma_is_not_available_even_if_installed() -> None:
    assert "chroma" not in MemoryProviderFactory.get_available_providers()


def test_explicit_chroma_selection_explains_safe_alternatives() -> None:
    with pytest.raises(MemoryProviderError, match="disabled due to unresolved upstream security advisories"):
        MemoryProviderFactory.create_provider({"provider": "chroma"})
