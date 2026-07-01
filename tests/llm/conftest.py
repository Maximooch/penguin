"""Pytest configuration for LLM tests.

pytest-asyncio is loaded through its installed pytest entry point. Keeping a
``pytest_plugins`` declaration in this nested conftest breaks collection on
current pytest versions because it affects the whole suite.
"""
