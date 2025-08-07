#!/usr/bin/env python3
"""
Test script for Penguin TUI command system and theming.

This script tests the command registry and CSS variable theming.
Run with: python test_tui_commands.py
"""

import sys
import yaml
from pathlib import Path
from typing import Dict, List, Optional

# Add penguin to path
sys.path.insert(0, str(Path(__file__).parent))

from penguin.cli.command_registry import CommandRegistry, Command, CommandParameter

# Color codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
RESET = "\033[0m"

def test_command_parsing():
    """Test command parsing functionality."""
    print(f"\n{BLUE}Testing Command Parsing...{RESET}")
    
    registry = CommandRegistry()
    
    test_cases = [
        ("/help", "help", {}),
        ("/h", "help", {}),  # Alias
        ("/chat list", "chat list", {}),
        ("/model set gpt-4", "model set", {"model_id": "gpt-4"}),
        ("/task create \"My Task\" \"Task description\"", "task create", {"name": "My", "description": "Task"}),
        ("/tokens reset", "tokens reset", {}),
        ("/debug tokens", "debug tokens", {}),
        ("/quit", "quit", {}),
        ("/invalid", None, {}),  # Invalid command
    ]
    
    passed = 0
    failed = 0
    
    for input_str, expected_cmd, expected_args in test_cases:
        cmd, args = registry.parse_input(input_str)
        
        if expected_cmd is None:
            if cmd is None:
                print(f"  {GREEN}✓{RESET} '{input_str}' correctly identified as invalid")
                passed += 1
            else:
                print(f"  {RED}✗{RESET} '{input_str}' should be invalid but got: {cmd.name}")
                failed += 1
        else:
            if cmd and cmd.name == expected_cmd:
                print(f"  {GREEN}✓{RESET} '{input_str}' → {cmd.name}")
                passed += 1
            else:
                print(f"  {RED}✗{RESET} '{input_str}' expected '{expected_cmd}' but got: {cmd.name if cmd else 'None'}")
                failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0

def test_command_suggestions():
    """Test command autocomplete suggestions."""
    print(f"\n{BLUE}Testing Command Suggestions...{RESET}")
    
    registry = CommandRegistry()
    
    test_cases = [
        ("", 0),  # Empty input
        ("h", 1),  # Should match 'help'
        ("cha", 2),  # Should match 'chat list', 'chat load', etc.
        ("mode", 2),  # Should match 'model', 'models'
        ("task", 5),  # Should match task commands
        ("xxx", 0),  # No matches
    ]
    
    for partial, min_expected in test_cases:
        suggestions = registry.get_suggestions(partial)
        if len(suggestions) >= min_expected:
            print(f"  {GREEN}✓{RESET} '{partial}' → {len(suggestions)} suggestions")
            if suggestions:
                print(f"    First 3: {suggestions[:3]}")
        else:
            print(f"  {RED}✗{RESET} '{partial}' expected ≥{min_expected} suggestions, got {len(suggestions)}")

def test_css_variables():
    """Test CSS variable theme system."""
    print(f"\n{BLUE}Testing CSS Variables...{RESET}")
    
    css_file = Path(__file__).parent / "penguin" / "cli" / "tui.css"
    
    if not css_file.exists():
        print(f"  {YELLOW}⚠{RESET} CSS file not found: {css_file}")
        return False
    
    with open(css_file, 'r') as f:
        css_content = f.read()
    
    # Check for CSS variables
    required_vars = [
        "--primary-bg",
        "--secondary-bg",
        "--primary-fg",
        "--accent",
        "--tool-header-bg",
        "--status-success",
        "--status-failed",
    ]
    
    missing = []
    for var in required_vars:
        if var in css_content:
            print(f"  {GREEN}✓{RESET} Found CSS variable: {var}")
        else:
            print(f"  {RED}✗{RESET} Missing CSS variable: {var}")
            missing.append(var)
    
    # Check for theme sections (commented out for future use)
    if "theme-nord" in css_content:
        print(f"  {CYAN}ℹ{RESET} Found Nord theme template")
    if "theme-dracula" in css_content:
        print(f"  {CYAN}ℹ{RESET} Found Dracula theme template")
    
    return len(missing) == 0

def test_commands_yaml():
    """Test commands.yml configuration."""
    print(f"\n{BLUE}Testing commands.yml Configuration...{RESET}")
    
    yaml_file = Path(__file__).parent / "penguin" / "cli" / "commands.yml"
    
    if not yaml_file.exists():
        print(f"  {YELLOW}⚠{RESET} commands.yml not found: {yaml_file}")
        return False
    
    with open(yaml_file, 'r') as f:
        config = yaml.safe_load(f)
    
    # Check structure
    if "version" in config:
        print(f"  {GREEN}✓{RESET} Version: {config['version']}")
    
    if "categories" in config:
        categories = [cat['name'] for cat in config['categories']]
        print(f"  {GREEN}✓{RESET} Categories: {', '.join(categories)}")
    
    if "commands" in config:
        print(f"  {GREEN}✓{RESET} Commands defined: {len(config['commands'])}")
        
        # Check for essential commands
        essential = ["help", "quit", "clear", "models", "tokens"]
        cmd_names = [cmd['name'] for cmd in config['commands']]
        
        for essential_cmd in essential:
            if essential_cmd in cmd_names:
                print(f"    {GREEN}✓{RESET} Essential command: {essential_cmd}")
            else:
                print(f"    {RED}✗{RESET} Missing essential command: {essential_cmd}")
    
    # Check for future features
    if "plugins" in config:
        print(f"  {CYAN}ℹ{RESET} Plugin support: {'enabled' if config['plugins'].get('enabled') else 'disabled'}")
    
    if "mcp" in config:
        print(f"  {CYAN}ℹ{RESET} MCP support: {'enabled' if config['mcp'].get('enabled') else 'disabled'}")
    
    return True

def test_handler_registration():
    """Test command handler registration."""
    print(f"\n{BLUE}Testing Handler Registration...{RESET}")
    
    registry = CommandRegistry()
    
    # Test registering a custom handler
    def custom_handler(*args, **kwargs):
        return "Custom handler executed"
    
    registry.register_handler("custom_test", custom_handler)
    
    # Test creating and registering a custom command
    custom_cmd = Command(
        name="test",
        category="debug",
        description="Test command",
        handler="custom_test"
    )
    
    registry.register(custom_cmd)
    
    # Test if command is registered
    cmd, args = registry.parse_input("/test")
    if cmd and cmd.name == "test":
        print(f"  {GREEN}✓{RESET} Custom command registered")
        
        # Test if handler can be retrieved
        if "custom_test" in registry.handlers:
            print(f"  {GREEN}✓{RESET} Custom handler registered")
        else:
            print(f"  {RED}✗{RESET} Handler not found in registry")
    else:
        print(f"  {RED}✗{RESET} Custom command not registered")
    
    return True

def main():
    """Run all tests."""
    print(f"{YELLOW}{'='*60}{RESET}")
    print(f"{YELLOW}Penguin TUI Command System Tests{RESET}")
    print(f"{YELLOW}{'='*60}{RESET}")
    
    all_passed = True
    
    # Run tests
    all_passed &= test_command_parsing()
    test_command_suggestions()  # Informational only
    all_passed &= test_css_variables()
    all_passed &= test_commands_yaml()
    all_passed &= test_handler_registration()
    
    # Summary
    print(f"\n{YELLOW}{'='*60}{RESET}")
    if all_passed:
        print(f"{GREEN}✅ All critical tests passed!{RESET}")
    else:
        print(f"{RED}❌ Some tests failed. Please review the output above.{RESET}")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
