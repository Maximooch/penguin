#!/usr/bin/env python3
"""Test script for sub-agent functionality.

Tests:
1. Config loading with agent personas
2. Persona model override (haiku-4.5 vs sonnet)
3. Tool restrictions (default_tools)
4. spawn_sub_agent action parsing
5. Sub-agent creation with persona
6. OpenRouter API verification for haiku-4.5
"""

import sys
import asyncio
import os
sys.path.insert(0, ".")

from penguin.config import Config
from penguin.core import PenguinCore


def test_config_personas():
    """Test that personas are loaded from config."""
    print("\n=== Test 1: Config Personas ===")

    config = Config.load_config()
    personas = config.agent_personas

    assert len(personas) >= 3, f"Expected at least 3 personas, got {len(personas)}"
    assert "researcher" in personas, "Missing 'researcher' persona"
    assert "implementer" in personas, "Missing 'implementer' persona"
    assert "reviewer" in personas, "Missing 'reviewer' persona"

    print(f"✓ Found {len(personas)} personas: {list(personas.keys())}")
    return True


def test_persona_model_override():
    """Test that personas have correct model settings."""
    print("\n=== Test 2: Persona Model Override ===")

    config = Config.load_config()

    researcher = config.agent_personas["researcher"]
    implementer = config.agent_personas["implementer"]

    # Check researcher uses haiku-4.5
    researcher_model = researcher.model.model if researcher.model else None
    assert "haiku" in (researcher_model or "").lower(), f"Researcher should use haiku, got: {researcher_model}"
    assert "4.5" in (researcher_model or "") or "haiku-4.5" in (researcher_model or "").lower(), f"Researcher should use haiku-4.5, got: {researcher_model}"
    print(f"✓ Researcher model: {researcher_model}")

    # Check implementer uses sonnet
    implementer_model = implementer.model.model if implementer.model else None
    assert "sonnet" in (implementer_model or "").lower(), f"Implementer should use sonnet, got: {implementer_model}"
    print(f"✓ Implementer model: {implementer_model}")

    return True


def test_persona_tool_restrictions():
    """Test that personas have correct tool restrictions."""
    print("\n=== Test 3: Persona Tool Restrictions ===")

    config = Config.load_config()

    researcher = config.agent_personas["researcher"]
    implementer = config.agent_personas["implementer"]

    # Researcher should have read-only tools
    researcher_tools = researcher.default_tools or []
    assert "enhanced_read" in researcher_tools, "Researcher should have enhanced_read"
    assert "enhanced_write" not in researcher_tools, "Researcher should NOT have enhanced_write"
    assert "execute" not in researcher_tools, "Researcher should NOT have execute"
    print(f"✓ Researcher tools (read-only): {researcher_tools}")

    # Implementer should have write tools
    implementer_tools = implementer.default_tools or []
    assert "enhanced_write" in implementer_tools or "apply_diff" in implementer_tools, "Implementer should have write tools"
    assert "execute" in implementer_tools or "execute_command" in implementer_tools, "Implementer should have execute"
    print(f"✓ Implementer tools (full access): {implementer_tools}")

    return True


def test_persona_context_limits():
    """Test that personas have context window limits."""
    print("\n=== Test 4: Persona Context Limits ===")

    config = Config.load_config()

    researcher = config.agent_personas["researcher"]
    implementer = config.agent_personas["implementer"]

    researcher_limit = researcher.shared_context_window_max_tokens
    implementer_limit = implementer.shared_context_window_max_tokens

    assert researcher_limit is not None, "Researcher should have context limit"
    assert implementer_limit is not None, "Implementer should have context limit"
    assert researcher_limit < implementer_limit, f"Researcher limit ({researcher_limit}) should be less than implementer ({implementer_limit})"

    print(f"✓ Researcher context limit: {researcher_limit}")
    print(f"✓ Implementer context limit: {implementer_limit}")

    return True


async def test_core_persona_catalog():
    """Test that core returns persona catalog correctly."""
    print("\n=== Test 5: Core Persona Catalog ===")

    config = Config.load_config()
    core = PenguinCore(config=config)

    catalog = core.get_persona_catalog()

    assert len(catalog) >= 3, f"Expected at least 3 personas in catalog, got {len(catalog)}"

    names = [p.get("name") for p in catalog]
    assert "researcher" in names, "Catalog missing 'researcher'"
    assert "implementer" in names, "Catalog missing 'implementer'"

    # Check catalog entries have required fields
    for entry in catalog:
        assert "name" in entry, f"Catalog entry missing 'name': {entry}"
        assert "description" in entry, f"Catalog entry missing 'description': {entry}"

    print(f"✓ Catalog has {len(catalog)} personas with correct structure")
    return True


async def test_register_agent_with_persona():
    """Test registering an agent with a persona."""
    print("\n=== Test 6: Register Agent with Persona ===")

    config = Config.load_config()
    core = PenguinCore(config=config)

    # Register an agent with researcher persona
    core.register_agent(
        "test-researcher-agent",
        persona="researcher",
        activate=False
    )

    # Check agent was registered
    roster = core.get_agent_roster()

    # Debug: show what we got
    print(f"  Roster entries: {len(roster)}")
    for entry in roster:
        print(f"    - id={entry.get('id')}, persona={entry.get('persona')}")

    # Note: get_agent_roster returns 'id' not 'agent_id'
    agent_ids = [a.get("id") for a in roster]

    assert "test-researcher-agent" in agent_ids, f"Agent not in roster: {agent_ids}"

    # Find the agent entry
    agent_entry = next(a for a in roster if a.get("id") == "test-researcher-agent")
    print(f"✓ Registered agent: {agent_entry.get('id')}")
    print(f"  Persona: {agent_entry.get('persona')}")

    return True


async def test_create_sub_agent_with_persona():
    """Test creating a sub-agent with a persona."""
    print("\n=== Test 7: Create Sub-Agent with Persona ===")

    config = Config.load_config()
    core = PenguinCore(config=config)

    # Create sub-agent with researcher persona
    core.create_sub_agent(
        "test-sub-researcher",
        parent_agent_id="default",
        persona="researcher",
        share_session=False,
        share_context_window=False,
    )

    # Check sub-agent was created
    roster = core.get_agent_roster()

    # Debug: show what we got
    print(f"  Roster entries: {len(roster)}")
    for entry in roster:
        print(f"    - id={entry.get('id')}, parent={entry.get('parent')}, persona={entry.get('persona')}")

    # Note: get_agent_roster returns 'id' not 'agent_id'
    agent_ids = [a.get("id") for a in roster]

    assert "test-sub-researcher" in agent_ids, f"Sub-agent not in roster: {agent_ids}"

    # Find the sub-agent entry
    sub_agent = next(a for a in roster if a.get("id") == "test-sub-researcher")
    print(f"✓ Created sub-agent: {sub_agent.get('id')}")
    print(f"  Parent: {sub_agent.get('parent')}")
    print(f"  Persona: {sub_agent.get('persona')}")

    return True


def test_openrouter_haiku_api():
    """Test that haiku-4.5 works via OpenRouter API."""
    print("\n=== Test 8: OpenRouter Haiku-4.5 API ===")

    import requests

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("⚠ OPENROUTER_API_KEY not set, skipping API test")
        return True  # Skip but don't fail

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "anthropic/claude-haiku-4.5",
            "messages": [{"role": "user", "content": "Say 'test passed' and nothing else"}],
            "max_tokens": 20
        },
        timeout=30
    )

    assert response.status_code == 200, f"API call failed: {response.status_code} - {response.text}"

    data = response.json()
    model_used = data.get("model", "")
    content = data["choices"][0]["message"]["content"]

    print(f"✓ API call successful")
    print(f"  Model used: {model_used}")
    print(f"  Response: {content}")

    # Verify it's actually haiku
    assert "haiku" in model_used.lower(), f"Expected haiku model, got: {model_used}"

    return True


def run_tests():
    """Run all tests."""
    print("=" * 60)
    print("SUB-AGENT FUNCTIONALITY TESTS")
    print("=" * 60)

    tests = [
        ("Config Personas", test_config_personas),
        ("Persona Model Override", test_persona_model_override),
        ("Persona Tool Restrictions", test_persona_tool_restrictions),
        ("Persona Context Limits", test_persona_context_limits),
        ("Core Persona Catalog", test_core_persona_catalog),
        ("Register Agent with Persona", test_register_agent_with_persona),
        ("Create Sub-Agent with Persona", test_create_sub_agent_with_persona),
        ("OpenRouter Haiku-4.5 API", test_openrouter_haiku_api),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            if asyncio.iscoroutinefunction(test_func):
                result = asyncio.run(test_func())
            else:
                result = test_func()

            if result:
                passed += 1
        except Exception as e:
            print(f"\n✗ FAILED: {name}")
            print(f"  Error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
