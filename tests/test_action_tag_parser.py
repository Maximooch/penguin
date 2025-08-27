#!/usr/bin/env python3
"""
Test script to verify action tag detection consistency between parser.py and openrouter_gateway.py

This ensures that both modules recognize the same action tags and handle them correctly.

Run with: python test_action_tag_parser.py
"""

import sys
import re
from pathlib import Path

# Add the penguin directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from penguin.utils.parser import ActionType, parse_action
from penguin.llm.openrouter_gateway import OpenRouterGateway
from penguin.llm.model_config import ModelConfig

def test_action_type_coverage():
    """Test that we have good coverage of action types."""
    print("=== Testing ActionType Enum Coverage ===")
    
    all_actions = list(ActionType)
    print(f"Total action types defined: {len(all_actions)}")
    
    # Show all action types
    for action in all_actions:
        print(f"  - {action.value}")
    
    # Check for common patterns
    common_categories = {
        "file_operations": ["read", "write", "create", "list", "find"],
        "execution": ["execute", "command"],
        "search": ["search", "memory", "workspace"],
        "project_mgmt": ["task", "project"],
        "browser": ["browser", "navigate", "screenshot"],
        "git": ["repository", "commit", "branch"],
    }
    
    print(f"\nAction categories coverage:")
    for category, keywords in common_categories.items():
        matching = [a.value for a in all_actions if any(kw in a.value.lower() for kw in keywords)]
        print(f"  {category}: {len(matching)} actions")
        for action in matching[:3]:  # Show first 3
            print(f"    - {action}")
        if len(matching) > 3:
            print(f"    ... and {len(matching) - 3} more")
    
    print("✅ Action type coverage analyzed\n")

def test_parser_detection():
    """Test that parser correctly detects action tags."""
    print("=== Testing Parser Action Detection ===")
    
    # Generate test cases for all action types
    test_cases = []
    
    # Test a sample of action types (not all to keep output manageable)
    sample_actions = [
        ActionType.EXECUTE,
        ActionType.SEARCH, 
        ActionType.MEMORY_SEARCH,
        ActionType.TASK_CREATE,
        ActionType.BROWSER_NAVIGATE,
        ActionType.ENHANCED_READ,
        ActionType.PROJECT_LIST,
    ]
    
    for action in sample_actions:
        tag = action.value
        # Create test content with this action
        content = f"I'll help you with that. <{tag}>some parameters</{tag}> Let me know if you need more help."
        test_cases.append((content, action, True))
    
    # Test invalid/non-existent actions
    invalid_tests = [
        ("No action tags here", None, False),
        ("<invalid_action>content</invalid_action>", None, False),
        ("<div>HTML tag</div>", None, False),
        ("Partial <execute> without closing", ActionType.EXECUTE, True),  # Should still detect
    ]
    test_cases.extend(invalid_tests)
    
    print(f"Testing {len(test_cases)} cases:")
    
    for i, (content, expected_action, should_find) in enumerate(test_cases, 1):
        actions = parse_action(content)
        found = len(actions) > 0
        
        if should_find and found:
            status = "✅"
            if expected_action and actions[0].action_type == expected_action:
                detail = f"Found {actions[0].action_type.value}"
            else:
                detail = f"Found {actions[0].action_type.value} (unexpected)"
        elif not should_find and not found:
            status = "✅"
            detail = "No actions found (expected)"
        else:
            status = "❌"
            detail = f"Expected find={should_find}, got find={found}"
        
        print(f"  {i:2d}. {status} {content[:40]:<40} | {detail}")
    
    print("✅ Parser detection tests completed\n")

def test_gateway_detection():
    """Test that gateway detection matches parser."""
    print("=== Testing Gateway vs Parser Consistency ===")
    
    # Create mock gateway for testing
    config = ModelConfig(
        model="test-model",
        provider="openrouter", 
        client_preference="openrouter"
    )
    gateway = OpenRouterGateway.__new__(OpenRouterGateway)
    
    # Test the same content with both parser and gateway
    test_contents = [
        "<execute>ls -la</execute>",
        "<search>python function</search>",
        "<memory_search>project details</memory_search>", 
        "<task_create>New task:Description</task_create>",
        "<browser_navigate>https://example.com</browser_navigate>",
        "<project_list></project_list>",
        "<enhanced_read>file.py</enhanced_read>",
        "Regular text without tags",
        "<invalid_tag>content</invalid_tag>",
        "Mixed <execute>command</execute> with other text",
        "<EXECUTE>uppercase tags</EXECUTE>",  # Test case sensitivity
    ]
    
    print("Comparing parser vs gateway detection:")
    print(f"{'Content':<40} | {'Parser':<8} | {'Gateway':<8} | {'Match'}")
    print("-" * 70)
    
    mismatches = 0
    for content in test_contents:
        # Test with parser
        parser_actions = parse_action(content)
        parser_found = len(parser_actions) > 0
        
        # Test with gateway
        gateway_found = gateway._contains_penguin_action_tags(content)
        
        # Check consistency
        match = parser_found == gateway_found
        match_symbol = "✅" if match else "❌"
        
        if not match:
            mismatches += 1
        
        print(f"{content[:38]:<40} | {str(parser_found):<8} | {str(gateway_found):<8} | {match_symbol}")
    
    if mismatches == 0:
        print(f"\n✅ Perfect consistency! Parser and gateway agree on all {len(test_contents)} test cases")
    else:
        print(f"\n⚠️  Found {mismatches} mismatches out of {len(test_contents)} cases")
    
    print()

def test_regex_patterns():
    """Test the regex patterns used by both parser and gateway."""
    print("=== Testing Regex Pattern Generation ===")
    
    # Test pattern generation like parser does
    action_tag_pattern = "|".join([action_type.value for action_type in ActionType])
    full_pattern = f"<({action_tag_pattern})>.*?</\\1>"
    opening_pattern = f"<({action_tag_pattern})>"
    
    print(f"Generated pattern length: {len(action_tag_pattern)} chars")
    print(f"Number of actions in pattern: {len(list(ActionType))}")
    print(f"Sample pattern start: {action_tag_pattern[:100]}...")
    print(f"Sample pattern end: ...{action_tag_pattern[-50:]}")
    
    # Test pattern compilation
    try:
        full_regex = re.compile(full_pattern, re.DOTALL | re.IGNORECASE)
        opening_regex = re.compile(opening_pattern, re.IGNORECASE)
        print("✅ Regex patterns compile successfully")
    except Exception as e:
        print(f"❌ Regex compilation failed: {e}")
        return
    
    # Test pattern matching on sample content
    test_content = """
    Here's my plan:
    <execute>echo "Hello World"</execute>
    
    Then I'll search:
    <search>python async patterns</search>
    
    And maybe create a task:
    <task_create>Review code:Check the implementation</task_create>
    """
    
    full_matches = full_regex.findall(test_content)
    opening_matches = opening_regex.findall(test_content)
    
    print(f"\nPattern matching results:")
    print(f"  Full tag matches: {len(full_matches)} -> {full_matches}")
    print(f"  Opening tag matches: {len(opening_matches)} -> {opening_matches}")
    
    # Verify they match expected actions
    expected_actions = ["execute", "search", "task_create"]
    if set(opening_matches) == set(expected_actions):
        print("✅ Pattern matching works correctly")
    else:
        print(f"⚠️  Expected {expected_actions}, got {opening_matches}")
    
    print()

def test_edge_cases():
    """Test edge cases that might cause issues."""
    print("=== Testing Edge Cases ===")
    
    edge_cases = [
        # Nested tags
        ("<execute>echo '<search>nested</search>'</execute>", "Nested tags"),
        
        # Malformed tags
        ("<execute>no closing tag", "Unclosed tag"),
        ("</execute>closing without opening", "Closing without opening"),
        
        # Multiple actions
        ("<execute>cmd1</execute> and <search>query</search>", "Multiple actions"),
        
        # Empty actions
        ("<execute></execute>", "Empty action"),
        
        # Special characters
        ("<execute>echo 'special chars: !@#$%^&*()'</execute>", "Special characters"),
        
        # Very long content
        (f"<execute>{'x' * 1000}</execute>", "Very long action content"),
        
        # Case variations
        ("<EXECUTE>uppercase</EXECUTE>", "Uppercase tags"),
        ("<Execute>mixed case</Execute>", "Mixed case tags"),
        
        # Whitespace variations
        ("< execute >spaces in tag< /execute >", "Spaces in tags"),
        ("<execute>\n  multiline\n  content\n</execute>", "Multiline content"),
    ]
    
    config = ModelConfig(model="test", provider="openrouter", client_preference="openrouter")
    gateway = OpenRouterGateway.__new__(OpenRouterGateway)
    
    print(f"Testing {len(edge_cases)} edge cases:")
    
    for content, description in edge_cases:
        parser_actions = parse_action(content)
        gateway_detected = gateway._contains_penguin_action_tags(content)
        
        parser_found = len(parser_actions) > 0
        consistent = parser_found == gateway_detected
        
        status = "✅" if consistent else "⚠️ "
        print(f"  {status} {description:<25} | Parser: {parser_found} | Gateway: {gateway_detected}")
        
        if parser_found and len(parser_actions) > 0:
            print(f"       → Found: {[a.action_type.value for a in parser_actions]}")
    
    print()

if __name__ == "__main__":
    print("🧪 Testing Action Tag Parser Consistency\n")
    
    try:
        test_action_type_coverage()
        test_parser_detection()
        test_gateway_detection()
        test_regex_patterns()
        test_edge_cases()
        
        print("🎉 All action tag tests completed!")
        
    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
    except Exception as e:
        print(f"💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()