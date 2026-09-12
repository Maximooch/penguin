"""The hosted integration never falls back to process credentials."""

import asyncio
from dataclasses import replace
from unittest.mock import Mock

import pytest

from penguin.project.contribution_auth import (
    ContributionBinding,
    contribution_scope,
    get_contribution_binding,
)
from penguin.project.github_operations import github_app_client, local_github_client
from penguin.project.repository_checkout import RepositoryError


def test_hosted_never_reads_keys_or_local_auth(monkeypatch):
    monkeypatch.setenv("PENGUIN_TOOL_ENVIRONMENT", "hosted")
    read = Mock(side_effect=AssertionError("must not read credentials"))
    monkeypatch.setattr("penguin.project.github_operations.get_api_key", read)
    with pytest.raises(RepositoryError, match="execution broker"):
        local_github_client()
    with pytest.raises(RepositoryError, match="execution broker"):
        github_app_client("123", "/must-not-open", "456")
    read.assert_not_called()


def test_incomplete_app_config_does_not_fall_back(monkeypatch):
    monkeypatch.setattr(
        "penguin.project.github_operations.get_api_key",
        lambda name: {"GITHUB_APP_ID": "123", "GITHUB_TOKEN": "fallback"}.get(name),
    )
    with pytest.raises(RepositoryError, match="Incomplete"):
        local_github_client()


def test_scope_restores_and_rejects_mismatch(tmp_path):
    binding = ContributionBinding(
        "run-a", "change-a", "owner/repo", tmp_path, "trunk", "a" * 40, Mock()
    )
    with contribution_scope(binding):
        assert get_contribution_binding("owner/repo", tmp_path) is binding
        with pytest.raises(RepositoryError):
            get_contribution_binding("other/repo", tmp_path)
        with pytest.raises(RepositoryError):
            get_contribution_binding("owner/repo", tmp_path / "other")
        with pytest.raises(RuntimeError):
            with contribution_scope(replace(binding, execution_id="run-b")):
                raise RuntimeError()
        assert get_contribution_binding("owner/repo", tmp_path) is binding
    assert get_contribution_binding("owner/repo", tmp_path) is None


@pytest.mark.asyncio
async def test_concurrent_scopes_propagate_to_threads(tmp_path):
    async def invoke(name):
        binding = ContributionBinding(
            name, name, "owner/repo", tmp_path, "trunk", "a" * 40, Mock()
        )
        with contribution_scope(binding):
            await asyncio.sleep(0)
            return await asyncio.to_thread(
                get_contribution_binding, "owner/repo", tmp_path
            )

    first, second = await asyncio.gather(invoke("first"), invoke("second"))
    assert first.execution_id == "first"
    assert second.execution_id == "second"
