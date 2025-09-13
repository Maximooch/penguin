import re


def test_system_prompt_contains_expected_sections_and_order():
    # Import lazily to avoid heavy imports during collection
    from penguin.penguin.system_prompt import SYSTEM_PROMPT

    assert isinstance(SYSTEM_PROMPT, str)
    assert len(SYSTEM_PROMPT) > 1000

    # Key section anchors (be tolerant to minor title wording)
    anchors = {
        "persistence": "Execution Persistence",
        "multistep": "## Multi-Step",
        "actions": "## Action Syntax",
    }

    for key, needle in anchors.items():
        assert needle in SYSTEM_PROMPT, f"Missing section: {key} ({needle})"

    # Verify order: persistence -> multistep -> actions
    idx_persist = SYSTEM_PROMPT.index(anchors["persistence"])  # must exist
    idx_multistep = SYSTEM_PROMPT.index(anchors["multistep"])  # must exist
    idx_actions = SYSTEM_PROMPT.index(anchors["actions"])  # must exist

    assert idx_persist < idx_multistep < idx_actions


def test_system_prompt_includes_essential_invariants_keywords():
    from penguin.penguin.system_prompt import SYSTEM_PROMPT

    # Core invariants keywords should be present
    keywords = [
        "Pre-write existence check",
        "apply_diff",  # prefer diffs / safe edits
        "allow/ask/deny",  # permission model mention
        "Post-verify touched files only",
    ]
    for k in keywords:
        assert k in SYSTEM_PROMPT, f"Missing invariant keyword: {k}"

