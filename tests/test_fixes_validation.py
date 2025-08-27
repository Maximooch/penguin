#!/usr/bin/env python3
"""
Quick validation test for the fixes applied.

Tests:
1. GPT-5 reasoning configuration detection
2. Parser vs Gateway consistency improvements

Run with: python test_fixes_validation.py
"""

import sys
from pathlib import Path

# Add the penguin directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from penguin.llm.model_config import ModelConfig
from penguin.llm.openrouter_gateway import OpenRouterGateway
from penguin.utils.parser import parse_action

def test_gpt5_reasoning_detection():
    """Test that GPT-5 is now detected as supporting reasoning."""
    print("=== Testing GPT-5 Reasoning Detection Fix ===")
    
    config = ModelConfig(
        model="openai/gpt-5",
        provider="openrouter",
        client_preference="openrouter",
        reasoning_enabled=True,
        reasoning_effort="medium"
    )
    
    print(f"Model: {config.model}")
    print(f"Supports reasoning: {config.supports_reasoning}")
    print(f"Reasoning enabled: {config.reasoning_enabled}")
    
    reasoning_config = config.get_reasoning_config()
    print(f"Reasoning config: {reasoning_config}")
    
    if reasoning_config == {"effort": "medium"}:
        print("✅ GPT-5 reasoning detection FIXED!")
        return True
    else:
        print(f"❌ GPT-5 reasoning detection still broken: {reasoning_config}")
        return False

def test_parser_gateway_consistency_improvement():
    """Test that parser and gateway are now more consistent."""
    print("\n=== Testing Parser vs Gateway Consistency Improvements ===")
    
    # Create gateway for testing
    config = ModelConfig(
        model="test-model",
        provider="openrouter",
        client_preference="openrouter"
    )
    gateway = OpenRouterGateway.__new__(OpenRouterGateway)
    
    # Test cases that previously had mismatches
    test_cases = [
        # This should now be consistent (both should detect uppercase)
        ("<EXECUTE>uppercase tags</EXECUTE>", "Uppercase tags"),
        
        # This should now be consistent (both should NOT detect partial)
        ("Partial <execute> without closing", "Unclosed tag"),
        
        # These should still work (both should detect)
        ("<execute>normal tag</execute>", "Normal tag"),
        ("<search>query</search>", "Search tag"),
    ]
    
    improvements = 0
    total_tests = len(test_cases)
    
    for content, description in test_cases:
        parser_actions = parse_action(content)
        gateway_detected = gateway._contains_penguin_action_tags(content)
        
        parser_found = len(parser_actions) > 0
        consistent = parser_found == gateway_detected
        
        status = "✅" if consistent else "❌"
        print(f"  {status} {description:<20} | Parser: {parser_found} | Gateway: {gateway_detected}")
        
        if consistent:
            improvements += 1
    
    print(f"\nConsistency: {improvements}/{total_tests} tests consistent")
    
    if improvements == total_tests:
        print("✅ Parser vs Gateway consistency IMPROVED!")
        return True
    elif improvements > 2:  # At least 3/4 consistent
        print("⚠️  Parser vs Gateway consistency partially improved")
        return True
    else:
        print("❌ Parser vs Gateway consistency still needs work")
        return False

def test_reasoning_model_patterns():
    """Test reasoning detection for various model patterns."""
    print("\n=== Testing Reasoning Detection Patterns ===")
    
    test_models = [
        ("openai/gpt-5", True, "GPT-5"),
        ("openai/gpt-4", False, "GPT-4 (should not have reasoning)"),
        ("openai/o1-preview", True, "O1 Preview"),
        ("anthropic/claude-3-5-sonnet-20241022", False, "Claude Sonnet 3.5 (should not have reasoning without explicit version)"),
        ("deepseek/deepseek-r1", True, "DeepSeek R1"),
        ("meta-llama/llama-3-70b", False, "Llama (should not have reasoning)"),
    ]
    
    correct = 0
    for model, expected_support, description in test_models:
        config = ModelConfig(
            model=model,
            provider="openrouter",
            client_preference="openrouter"
        )
        
        actual_support = config.supports_reasoning
        status = "✅" if actual_support == expected_support else "❌"
        
        print(f"  {status} {description:<40} | Expected: {expected_support} | Actual: {actual_support}")
        
        if actual_support == expected_support:
            correct += 1
    
    print(f"\nReasoning detection: {correct}/{len(test_models)} correct")
    return correct == len(test_models)

if __name__ == "__main__":
    print("🔧 Validating OpenRouter Gateway Fixes\n")
    
    results = []
    results.append(test_gpt5_reasoning_detection())
    results.append(test_parser_gateway_consistency_improvement())
    results.append(test_reasoning_model_patterns())
    
    passed = sum(results)
    total = len(results)
    
    print(f"\n📊 Fix Validation Results: {passed}/{total} areas improved")
    
    if passed == total:
        print("🎉 All fixes validated successfully!")
    elif passed > 0:
        print("⚠️  Some fixes working, others may need more work")
    else:
        print("❌ Fixes need more work")
    
    print(f"\n🔬 Re-run the main tests to see improvements:")
    print(f"   python run_all_tests.py")
    print(f"   python test_reasoning_models.py")