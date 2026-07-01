def test_system_prompt_contains_expected_sections_and_order():
    # Import lazily to avoid heavy imports during collection
    from penguin.system_prompt import SYSTEM_PROMPT

    assert isinstance(SYSTEM_PROMPT, str)
    assert len(SYSTEM_PROMPT) > 1000

    # Key section anchors in the current composed prompt.
    anchors = {
        "identity": "**Core Philosophy:**",
        "work_style": "**How You Work:**",
        "tool_protocol": "## Tool Invocation Protocol",
        "workflow": "## Development Workflow",
    }

    for key, needle in anchors.items():
        assert needle in SYSTEM_PROMPT, f"Missing section: {key} ({needle})"

    # Verify composition order: identity -> work style -> tools -> workflow.
    idx_identity = SYSTEM_PROMPT.index(anchors["identity"])
    idx_work_style = SYSTEM_PROMPT.index(anchors["work_style"])
    idx_tool_protocol = SYSTEM_PROMPT.index(anchors["tool_protocol"])
    idx_workflow = SYSTEM_PROMPT.index(anchors["workflow"])

    assert idx_identity < idx_work_style < idx_tool_protocol < idx_workflow


def test_system_prompt_includes_essential_invariants_keywords():
    from penguin.system_prompt import SYSTEM_PROMPT

    # Core invariants keywords should be present.
    keywords = [
        "Fact-based skepticism",
        "Surgical Changes",
        "apply_patch",
        "Use native tool calls first",
        "Completion Signals",
    ]
    for k in keywords:
        assert k in SYSTEM_PROMPT, f"Missing invariant keyword: {k}"
