#!/usr/bin/env python3
"""
Test script for Penguin TUI widgets.

This script tests the new widget system without requiring pytest.
Run with: python test_tui_widgets.py
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add penguin to path
sys.path.insert(0, str(Path(__file__).parent))

from penguin.cli.widgets import ToolExecutionWidget, StreamingStateMachine, StreamState
from penguin.cli.widgets.unified_display import (
    UnifiedExecution, ExecutionAdapter, ExecutionStatus, ExecutionType
)
from penguin.cli.command_registry import CommandRegistry

# Color codes for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

def print_test(test_name: str, passed: bool, details: str = ""):
    """Print test result."""
    status = f"{GREEN}✓ PASSED{RESET}" if passed else f"{RED}✗ FAILED{RESET}"
    print(f"{status} - {test_name}")
    if details:
        print(f"  {details}")

def test_unified_execution():
    """Test UnifiedExecution abstraction."""
    print(f"\n{BLUE}Testing UnifiedExecution...{RESET}")
    
    # Test basic creation
    exec = UnifiedExecution(
        id="test-1",
        name="test_tool",
        type=ExecutionType.TOOL,
        status=ExecutionStatus.PENDING,
        display_name="Test Tool",
        icon="🔧",
        parameters={"query": "test query"},
        started_at=datetime.now()
    )
    
    print_test("UnifiedExecution creation", exec.id == "test-1")
    print_test("Display name", exec.display_name == "Test Tool")
    print_test("Initial status", exec.status == ExecutionStatus.PENDING)
    
    # Test duration calculation
    import time
    time.sleep(0.1)
    exec.completed_at = datetime.now()
    duration_ms = exec.duration_ms
    print_test("Duration calculation", duration_ms is not None and duration_ms > 0, f"Duration: {exec.duration_str}")
    
    # Test to_display_dict
    display_dict = exec.to_display_dict()
    print_test("to_display_dict", "name" in display_dict and "status" in display_dict)

def test_execution_adapter():
    """Test ExecutionAdapter for different types."""
    print(f"\n{BLUE}Testing ExecutionAdapter...{RESET}")
    
    # Test from_tool
    tool_exec = ExecutionAdapter.from_tool(
        "workspace_search",
        {"query": "authentication", "max_results": 5}
    )
    print_test("from_tool", tool_exec.type == ExecutionType.TOOL)
    print_test("Tool icon mapping", tool_exec.icon == "🔍")
    
    # Test from_action with XML-style params (colon-separated)
    action_exec = ExecutionAdapter.from_action(
        "workspace_search",
        "authentication flow:10"  # XML tag content format
    )
    print_test("from_action", action_exec.type == ExecutionType.ACTION)
    print_test("Action param parsing", 
               action_exec.parameters.get("query") == "authentication flow",
               f"Parsed params: {action_exec.parameters}")
    print_test("Action max_results parsing", 
               action_exec.parameters.get("max_results") == 10)
    
    # Test execute action (raw code)
    execute_exec = ExecutionAdapter.from_action(
        "execute",
        "print('Hello World')\nx = 42"
    )
    print_test("Execute action", execute_exec.parameters.get("code") == "print('Hello World')\nx = 42")
    
    # Test enhanced_read action
    read_exec = ExecutionAdapter.from_action(
        "enhanced_read",
        "src/main.py:true:100"
    )
    print_test("Enhanced read parsing", 
               read_exec.parameters.get("path") == "src/main.py" and
               read_exec.parameters.get("show_line_numbers") == True,
               f"Params: {read_exec.parameters}")
    
    # Test memory_search action
    memory_exec = ExecutionAdapter.from_action(
        "memory_search",
        "database config:5:all:database,config"
    )
    print_test("Memory search parsing",
               memory_exec.parameters.get("query") == "database config" and
               memory_exec.parameters.get("k") == 5 and
               memory_exec.parameters.get("categories") == ["database", "config"],
               f"Params: {memory_exec.parameters}")
    
    # Test add_summary_note action
    note_exec = ExecutionAdapter.from_action(
        "add_summary_note",
        "decisions:We decided to use PostgreSQL for the database"
    )
    print_test("Summary note parsing",
               note_exec.parameters.get("category") == "decisions" and
               "PostgreSQL" in note_exec.parameters.get("content", ""),
               f"Params: {note_exec.parameters}")
    
    # Test from_system
    system_exec = ExecutionAdapter.from_system("System message")
    print_test("from_system", system_exec.type == ExecutionType.SYSTEM)
    print_test("System auto-complete", system_exec.status == ExecutionStatus.SUCCESS)
    
    # Test from_error
    error_exec = ExecutionAdapter.from_error("Test error", "Test context")
    print_test("from_error", error_exec.type == ExecutionType.ERROR)
    print_test("Error status", error_exec.status == ExecutionStatus.FAILED)

def test_streaming_state_machine():
    """Test StreamingStateMachine."""
    print(f"\n{BLUE}Testing StreamingStateMachine...{RESET}")
    
    sm = StreamingStateMachine()
    
    # Test initial state
    print_test("Initial state", sm.state == StreamState.IDLE)
    
    # Track chunks
    chunks_received = []
    sm.on_chunk = lambda c: chunks_received.append(c)
    
    # Process chunks
    sm.process_chunk("Hello ")
    print_test("State after first chunk", sm.state == StreamState.STREAMING)
    
    sm.process_chunk("world!")
    print_test("Buffer accumulation", "Hello world!" in sm.buffer)
    
    # Test final chunk
    final_content = None
    sm.on_complete = lambda c: globals().update(final_content=c)
    sm.process_chunk("", is_final=True)
    print_test("Final state", sm.state == StreamState.COMPLETE)
    
    # Test reset
    sm.reset()
    print_test("Reset", sm.state == StreamState.IDLE and sm.buffer == "")

def test_command_registry():
    """Test CommandRegistry system."""
    print(f"\n{BLUE}Testing CommandRegistry...{RESET}")
    
    # Test loading from YAML
    registry = CommandRegistry()
    
    # Test command lookup
    cmd, args = registry.parse_input("/help")
    print_test("Command lookup", cmd is not None and cmd.name == "help")
    
    # Test aliases
    cmd, args = registry.parse_input("/h")
    print_test("Alias resolution", cmd is not None and cmd.name == "help")
    
    # Test multi-word commands
    cmd, args = registry.parse_input("/chat list")
    print_test("Multi-word command", cmd is not None and cmd.name == "chat list")
    
    # Test command with arguments
    cmd, args = registry.parse_input("/model set gpt-4")
    print_test("Command arguments", cmd is not None and "model_id" in args, f"Args: {args}")
    
    # Test suggestions
    suggestions = registry.get_suggestions("cha")
    print_test("Command suggestions", len(suggestions) > 0, f"Found {len(suggestions)} suggestions")
    
    # Test help generation
    help_text = registry.get_help_text()
    print_test("Help text generation", "Available Commands" in help_text)

def test_action_parameter_parsing():
    """Test XML action tag parameter parsing."""
    print(f"\n{BLUE}Testing Action Parameter Parsing...{RESET}")
    
    # Test various action formats
    test_cases = [
        ("execute", "print('hello')", {"code": "print('hello')"}),
        ("execute_command", "ls -la", {"code": "ls -la"}),
        ("workspace_search", "auth flow:5", {"query": "auth flow", "max_results": 5}),
        ("memory_search", "test:3::", {"query": "test", "k": 3}),
        ("enhanced_read", "file.py:false:20", {"path": "file.py", "show_line_numbers": False, "max_lines": "20"}),
        ("enhanced_write", "file.py:content here:true", {"path": "file.py", "content": "content here", "backup": True}),
        ("add_declarative_note", "requirements:Must support Python 3.8+", 
         {"category": "requirements", "content": "Must support Python 3.8+"}),
        ("add_summary_note", "decisions:Using PostgreSQL", 
         {"category": "decisions", "content": "Using PostgreSQL"}),
        ("apply_diff", "main.py:--- a/main.py\n+++ b/main.py:false", 
         {"file_path": "main.py", "diff_content": "--- a/main.py\n+++ b/main.py", "backup": False}),
    ]
    
    for action_type, params_str, expected in test_cases:
        parsed = ExecutionAdapter._parse_action_params(action_type, params_str)
        match = all(parsed.get(k) == v for k, v in expected.items())
        print_test(f"{action_type} parsing", match, 
                  f"Expected: {expected}, Got: {parsed}" if not match else "")

def test_tool_execution_widget():
    """Test ToolExecutionWidget (basic validation)."""
    print(f"\n{BLUE}Testing ToolExecutionWidget...{RESET}")
    
    # Create a sample execution
    execution = UnifiedExecution(
        id="widget-test",
        name="test_widget",
        type=ExecutionType.TOOL,
        status=ExecutionStatus.RUNNING,
        display_name="Test Widget",
        parameters={"code": "print('hello')"},
        started_at=datetime.now()
    )
    
    # Create widget
    widget = ToolExecutionWidget(execution)
    print_test("Widget creation", widget is not None)
    print_test("Widget execution binding", widget.execution.id == "widget-test")
    
    # Test status update
    widget.update_status(ExecutionStatus.SUCCESS, result="Output: hello")
    print_test("Status update", widget.execution.status == ExecutionStatus.SUCCESS)
    print_test("Result update", widget.execution.result == "Output: hello")
    
    # Test language detection
    python_detected = widget._detect_language("def hello():\n    print('world')")
    print_test("Python detection", python_detected == "python")
    
    js_detected = widget._detect_language("function hello() { console.log('world'); }")
    print_test("JavaScript detection", js_detected == "javascript")

async def test_async_components():
    """Test async components."""
    print(f"\n{BLUE}Testing async components...{RESET}")
    
    # Test streaming state machine with async
    sm = StreamingStateMachine()
    
    # Simulate async streaming
    chunks = ["Chunk 1 ", "Chunk 2 ", "Final"]
    for i, chunk in enumerate(chunks):
        sm.process_chunk(chunk, is_final=(i == len(chunks) - 1))
        await asyncio.sleep(0.01)  # Simulate network delay
    
    print_test("Async streaming", sm.state == StreamState.COMPLETE, f"Processed {sm.chunk_count} chunks")

def main():
    """Run all tests."""
    print(f"{YELLOW}{'='*60}{RESET}")
    print(f"{YELLOW}Penguin TUI Widget Tests{RESET}")
    print(f"{YELLOW}{'='*60}{RESET}")
    
    try:
        # Run sync tests
        test_unified_execution()
        test_execution_adapter()
        test_streaming_state_machine()
        test_command_registry()
        test_action_parameter_parsing()  # New test for XML action parsing
        test_tool_execution_widget()
        
        # Run async tests
        asyncio.run(test_async_components())
        
        print(f"\n{GREEN}All tests completed!{RESET}")
        
    except Exception as e:
        print(f"\n{RED}Test failed with error: {e}{RESET}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
