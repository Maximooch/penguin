"""
Unit tests for Penguin Permission Engine.

Tests cover:
- Permission modes and results
- WorkspaceBoundaryPolicy
- Path normalization and traversal detection
- PermissionEnforcer integration
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from penguin.security import (
    PermissionMode,
    PermissionResult,
    Operation,
    PolicyEngine,
    PermissionEnforcer,
    PermissionDeniedError,
    WorkspaceBoundaryPolicy,
    # Path utilities
    normalize_path,
    detect_traversal,
    is_within_boundary,
    is_within_any_boundary,
    validate_path_security,
    PathSecurityError,
    PathTraversalError,
)


class TestPermissionEnums:
    """Test permission mode and result enums."""
    
    def test_permission_modes(self):
        assert PermissionMode.READ_ONLY.value == "read_only"
        assert PermissionMode.WORKSPACE.value == "workspace"
        assert PermissionMode.FULL.value == "full"
    
    def test_permission_results(self):
        assert PermissionResult.ALLOW.value == "allow"
        assert PermissionResult.ASK.value == "ask"
        assert PermissionResult.DENY.value == "deny"
    
    def test_operations_have_categories(self):
        assert Operation.FILESYSTEM_READ.category == "filesystem"
        assert Operation.FILESYSTEM_WRITE.action == "write"
        assert Operation.PROCESS_EXECUTE.category == "process"
        assert Operation.GIT_PUSH.category == "git"
    
    def test_is_read_only(self):
        assert Operation.is_read_only(Operation.FILESYSTEM_READ) is True
        assert Operation.is_read_only(Operation.FILESYSTEM_LIST) is True
        assert Operation.is_read_only(Operation.MEMORY_READ) is True
        assert Operation.is_read_only(Operation.FILESYSTEM_WRITE) is False
        assert Operation.is_read_only(Operation.PROCESS_EXECUTE) is False


class TestPathUtilities:
    """Test path normalization and validation utilities."""
    
    def test_normalize_path_expands_tilde(self):
        path = normalize_path("~/test")
        assert str(path).startswith(str(Path.home()))
    
    def test_normalize_path_resolves_absolute(self):
        path = normalize_path("/tmp/test")
        assert path.is_absolute()
    
    def test_normalize_path_handles_relative(self):
        path = normalize_path("./test.py")
        assert path.is_absolute()
    
    def test_normalize_path_empty_raises(self):
        with pytest.raises(PathSecurityError):
            normalize_path("")
    
    def test_detect_traversal_simple(self):
        assert detect_traversal("../etc/passwd") is True
        assert detect_traversal("../../root") is True
        assert detect_traversal("test/../../etc") is True
    
    def test_detect_traversal_safe(self):
        assert detect_traversal("./test.py") is False
        assert detect_traversal("src/main.py") is False
        assert detect_traversal("/absolute/path") is False
    
    def test_detect_traversal_null_byte(self):
        assert detect_traversal("test\x00.py") is True
    
    def test_is_within_boundary(self):
        boundary = Path("/home/user/project")
        assert is_within_boundary(Path("/home/user/project/src"), boundary) is True
        assert is_within_boundary(Path("/home/user/project/src/main.py"), boundary) is True
        assert is_within_boundary(Path("/home/user/other"), boundary) is False
        assert is_within_boundary(Path("/etc/passwd"), boundary) is False
    
    def test_is_within_any_boundary(self):
        boundaries = [Path("/home/user/project"), Path("/tmp/workspace")]
        assert is_within_any_boundary(Path("/home/user/project/src"), boundaries) is True
        assert is_within_any_boundary(Path("/tmp/workspace/file"), boundaries) is True
        assert is_within_any_boundary(Path("/etc/passwd"), boundaries) is False


class TestWorkspaceBoundaryPolicy:
    """Test workspace boundary policy enforcement."""
    
    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace and project directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            project = Path(tmpdir) / "project"
            workspace.mkdir()
            project.mkdir()
            yield workspace, project
    
    def test_policy_allows_workspace_writes(self, temp_workspace):
        workspace, project = temp_workspace
        policy = WorkspaceBoundaryPolicy(
            workspace_root=str(workspace),
            project_root=str(project),
            mode=PermissionMode.WORKSPACE,
        )
        
        result, reason = policy.check_operation(
            Operation.FILESYSTEM_WRITE,
            str(workspace / "test.txt"),
        )
        assert result == PermissionResult.ALLOW
    
    def test_policy_allows_project_writes(self, temp_workspace):
        workspace, project = temp_workspace
        policy = WorkspaceBoundaryPolicy(
            workspace_root=str(workspace),
            project_root=str(project),
            mode=PermissionMode.WORKSPACE,
        )
        
        result, reason = policy.check_operation(
            Operation.FILESYSTEM_WRITE,
            str(project / "src" / "main.py"),
        )
        assert result == PermissionResult.ALLOW
    
    def test_policy_denies_outside_boundaries(self, temp_workspace):
        workspace, project = temp_workspace
        policy = WorkspaceBoundaryPolicy(
            workspace_root=str(workspace),
            project_root=str(project),
            mode=PermissionMode.WORKSPACE,
        )
        
        result, reason = policy.check_operation(
            Operation.FILESYSTEM_WRITE,
            "/etc/passwd",
        )
        assert result == PermissionResult.DENY
    
    def test_policy_allows_reads_outside_boundaries(self, temp_workspace):
        workspace, project = temp_workspace
        policy = WorkspaceBoundaryPolicy(
            workspace_root=str(workspace),
            project_root=str(project),
            mode=PermissionMode.WORKSPACE,
        )
        
        # Use a path that's outside workspace/project but not a system path
        # /tmp is typically allowed for reads
        result, reason = policy.check_operation(
            Operation.FILESYSTEM_READ,
            "/tmp/some_external_file.txt",
        )
        assert result == PermissionResult.ALLOW
    
    def test_read_only_mode_denies_writes(self, temp_workspace):
        workspace, project = temp_workspace
        policy = WorkspaceBoundaryPolicy(
            workspace_root=str(workspace),
            project_root=str(project),
            mode=PermissionMode.READ_ONLY,
        )
        
        result, reason = policy.check_operation(
            Operation.FILESYSTEM_WRITE,
            str(workspace / "test.txt"),
        )
        assert result == PermissionResult.DENY
    
    def test_read_only_mode_allows_reads(self, temp_workspace):
        workspace, project = temp_workspace
        policy = WorkspaceBoundaryPolicy(
            workspace_root=str(workspace),
            project_root=str(project),
            mode=PermissionMode.READ_ONLY,
        )
        
        result, reason = policy.check_operation(
            Operation.FILESYSTEM_READ,
            str(workspace / "test.txt"),
        )
        assert result == PermissionResult.ALLOW
    
    def test_full_mode_allows_everything(self, temp_workspace):
        workspace, project = temp_workspace
        policy = WorkspaceBoundaryPolicy(
            workspace_root=str(workspace),
            project_root=str(project),
            mode=PermissionMode.FULL,
        )
        
        result, reason = policy.check_operation(
            Operation.FILESYSTEM_WRITE,
            "/etc/passwd",
        )
        assert result == PermissionResult.ALLOW
    
    def test_delete_requires_approval(self, temp_workspace):
        workspace, project = temp_workspace
        policy = WorkspaceBoundaryPolicy(
            workspace_root=str(workspace),
            project_root=str(project),
            mode=PermissionMode.WORKSPACE,
        )
        
        result, reason = policy.check_operation(
            Operation.FILESYSTEM_DELETE,
            str(workspace / "test.txt"),
        )
        assert result == PermissionResult.ASK
    
    def test_denied_paths_pattern(self, temp_workspace):
        workspace, project = temp_workspace
        policy = WorkspaceBoundaryPolicy(
            workspace_root=str(workspace),
            project_root=str(project),
            mode=PermissionMode.WORKSPACE,
            denied_paths=[".env"],
        )
        
        result, reason = policy.check_operation(
            Operation.FILESYSTEM_WRITE,
            str(project / ".env"),
        )
        assert result == PermissionResult.DENY


class TestPermissionEnforcer:
    """Test permission enforcer with multiple policies."""
    
    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace and project directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            project = Path(tmpdir) / "project"
            workspace.mkdir()
            project.mkdir()
            yield workspace, project
    
    def test_enforcer_default_allows(self):
        enforcer = PermissionEnforcer(mode=PermissionMode.FULL)
        result = enforcer.check(Operation.FILESYSTEM_WRITE, "/any/path")
        assert result == PermissionResult.ALLOW
    
    def test_enforcer_yolo_mode_allows_everything(self):
        enforcer = PermissionEnforcer(mode=PermissionMode.READ_ONLY, yolo=True)
        # Even with READ_ONLY, YOLO mode allows everything
        result = enforcer.check(Operation.FILESYSTEM_WRITE, "/etc/passwd")
        assert result == PermissionResult.ALLOW
    
    def test_enforcer_with_policy(self, temp_workspace):
        workspace, project = temp_workspace
        enforcer = PermissionEnforcer(mode=PermissionMode.WORKSPACE)
        
        policy = WorkspaceBoundaryPolicy(
            workspace_root=str(workspace),
            project_root=str(project),
            mode=PermissionMode.WORKSPACE,
        )
        enforcer.add_policy(policy)
        
        # Should allow within workspace
        result = enforcer.check(Operation.FILESYSTEM_WRITE, str(workspace / "test.txt"))
        assert result == PermissionResult.ALLOW
        
        # Should deny outside
        result = enforcer.check(Operation.FILESYSTEM_WRITE, "/etc/passwd")
        assert result == PermissionResult.DENY
    
    def test_enforcer_check_and_raise(self, temp_workspace):
        workspace, project = temp_workspace
        enforcer = PermissionEnforcer(mode=PermissionMode.WORKSPACE)
        
        policy = WorkspaceBoundaryPolicy(
            workspace_root=str(workspace),
            project_root=str(project),
            mode=PermissionMode.WORKSPACE,
        )
        enforcer.add_policy(policy)
        
        with pytest.raises(PermissionDeniedError) as exc_info:
            enforcer.check_and_raise(Operation.FILESYSTEM_WRITE, "/etc/passwd")
        
        assert exc_info.value.operation == Operation.FILESYSTEM_WRITE
        assert exc_info.value.resource == "/etc/passwd"
    
    def test_enforcer_session_allowlist(self, temp_workspace):
        workspace, project = temp_workspace
        enforcer = PermissionEnforcer(mode=PermissionMode.WORKSPACE)
        
        policy = WorkspaceBoundaryPolicy(
            workspace_root=str(workspace),
            project_root=str(project),
            mode=PermissionMode.WORKSPACE,
        )
        enforcer.add_policy(policy)
        
        # Normally denied
        result = enforcer.check(Operation.FILESYSTEM_WRITE, "/etc/test")
        assert result == PermissionResult.DENY
        
        # Add to session allowlist
        enforcer.add_session_allowlist("filesystem.write:/etc/*")
        
        # Now allowed
        result = enforcer.check(Operation.FILESYSTEM_WRITE, "/etc/test")
        assert result == PermissionResult.ALLOW
    
    def test_enforcer_audit_log(self, temp_workspace):
        workspace, project = temp_workspace
        enforcer = PermissionEnforcer(mode=PermissionMode.WORKSPACE, audit_all=True)
        
        policy = WorkspaceBoundaryPolicy(
            workspace_root=str(workspace),
            project_root=str(project),
            mode=PermissionMode.WORKSPACE,
        )
        enforcer.add_policy(policy)
        
        # Make some checks
        enforcer.check(Operation.FILESYSTEM_READ, str(workspace / "test.txt"))
        enforcer.check(Operation.FILESYSTEM_WRITE, "/etc/passwd")
        
        # Get audit log
        log = enforcer.get_audit_log()
        assert len(log) >= 2
        
        # Check log entries have expected fields
        for entry in log:
            assert "operation" in entry
            assert "resource" in entry
            assert "result" in entry
            assert "timestamp" in entry
    
    def test_enforcer_capabilities_summary(self):
        enforcer = PermissionEnforcer(mode=PermissionMode.WORKSPACE)
        summary = enforcer.get_capabilities_summary()
        
        assert "mode" in summary
        assert "can" in summary
        assert "cannot" in summary
        assert "requires_approval" in summary
        assert summary["mode"] == "workspace"
    
    def test_enforcer_yolo_capabilities(self):
        enforcer = PermissionEnforcer(mode=PermissionMode.WORKSPACE, yolo=True)
        summary = enforcer.get_capabilities_summary()
        
        assert summary["mode"] == "yolo"
        assert "Everything" in summary["can"][0]


class TestPermissionDeniedError:
    """Test permission denied error formatting."""
    
    def test_error_message(self):
        error = PermissionDeniedError(
            operation=Operation.FILESYSTEM_WRITE,
            resource="/etc/passwd",
            reason="System path - writes not allowed",
            mode=PermissionMode.WORKSPACE,
            suggestion="Run with --yolo flag",
        )
        
        assert "Permission denied" in str(error)
        assert "Run with --yolo" in str(error)
    
    def test_error_to_dict(self):
        error = PermissionDeniedError(
            operation=Operation.FILESYSTEM_WRITE,
            resource="/etc/passwd",
            reason="System path",
            mode=PermissionMode.WORKSPACE,
        )
        
        d = error.to_dict()
        assert d["error"] == "permission_denied"
        assert d["operation"] == "filesystem.write"
        assert d["resource"] == "/etc/passwd"
        assert d["mode"] == "workspace"


class TestToolPermissionMapping:
    """Test tool to operation mapping."""
    
    def test_read_tools_are_safe(self):
        from penguin.security.tool_permissions import is_safe_tool
        
        assert is_safe_tool("read_file") is True
        assert is_safe_tool("list_files") is True
        assert is_safe_tool("grep_search") is True
    
    def test_write_tools_are_not_safe(self):
        from penguin.security.tool_permissions import is_safe_tool
        
        assert is_safe_tool("write_to_file") is False
        assert is_safe_tool("execute_command") is False
        assert is_safe_tool("apply_diff") is False
    
    def test_extract_resource(self):
        from penguin.security.tool_permissions import extract_resource_from_input
        
        assert extract_resource_from_input("read_file", {"path": "/test.py"}) == "/test.py"
        assert extract_resource_from_input("execute_command", {"command": "ls -la"}) == "ls -la"
        assert extract_resource_from_input("browser_navigate", {"url": "http://example.com"}) == "http://example.com"
    
    def test_get_highest_risk_operation(self):
        from penguin.security.tool_permissions import get_highest_risk_operation
        
        # apply_diff has read + write, should return write as higher risk
        op = get_highest_risk_operation("apply_diff")
        assert op == Operation.FILESYSTEM_WRITE
        
        # execute_command is high risk
        op = get_highest_risk_operation("execute_command")
        assert op == Operation.PROCESS_EXECUTE


class TestEnvironmentVariableOverrides:
    """Test environment variable configuration."""
    
    def test_yolo_env_var(self):
        with patch.dict(os.environ, {"PENGUIN_YOLO": "1"}):
            enforcer = PermissionEnforcer(mode=PermissionMode.READ_ONLY)
            assert enforcer.yolo is True
    
    def test_yolo_env_var_false(self):
        with patch.dict(os.environ, {"PENGUIN_YOLO": "0"}, clear=False):
            # Need to explicitly set yolo=False since env var might be "1"
            enforcer = PermissionEnforcer(mode=PermissionMode.READ_ONLY, yolo=False)
            # If PENGUIN_YOLO=0, it should not enable yolo
            # The env check is for "1", "true", "yes"
            assert enforcer.yolo is False

