"""Pytest configuration for LLM tests."""

import pytest

# Configure pytest-asyncio to use auto mode for async fixtures and tests
pytest_plugins = ('pytest_asyncio',)
