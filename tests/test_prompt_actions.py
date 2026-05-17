from __future__ import annotations

from penguin.prompt_actions import get_tool_guide
from penguin.prompt_workflow import get_workflow_guide
from penguin.tools.editing.registry import (
    get_edit_tool_public_names,
    get_edit_tool_schema_map,
)


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def test_tool_guide_includes_canonical_edit_headings() -> None:
    guide = get_tool_guide()

    for tool_name in get_edit_tool_public_names():
        assert f"### {tool_name}" in guide


def test_tool_guide_documents_native_tool_protocol_first() -> None:
    guide = get_tool_guide()

    assert "## Tool Invocation Protocol" in guide
    assert "Native provider tools" in guide
    assert "ActionXML fallback" in guide
    assert "Use native tool calls first" in guide


def test_completion_guidance_prefers_natural_turn_completion() -> None:
    guide = get_tool_guide()
    workflow = get_workflow_guide()
    normalized_workflow = _normalize_text(workflow)

    assert "Normal conversation turns complete" in guide
    assert "Not used for normal native-tool conversations" in guide
    assert "return final assistant text and make no further tool calls" in (
        normalized_workflow
    )
    assert "Never rely on implicit completion" not in workflow
    assert "call `finish_response` or `finish_task`" not in guide
    assert "call `finish_response` or `finish_task`" not in normalized_workflow


def test_tool_guide_uses_schema_derived_aliases_and_required_fields() -> None:
    guide = get_tool_guide()
    schemas = get_edit_tool_schema_map()

    assert "Required fields: `path`, `content`" in guide
    assert "Required fields: `path`, `old_string`, `new_string`" in guide
    assert "Required fields: `patch`" in guide

    for tool_name, schema in schemas.items():
        aliases = schema.get("aliases") or []
        if aliases:
            alias_fragment = ", ".join(f"`{alias}`" for alias in aliases)
            assert f"Legacy aliases: {alias_fragment}" in guide


def test_tool_guide_promotes_canonical_names_over_legacy_headers() -> None:
    guide = get_tool_guide()
    workflow = get_workflow_guide()

    assert "### enhanced_read" not in guide
    assert "### enhanced_write" not in guide
    assert "### apply_diff" not in guide
    assert "### multiedit" not in guide
    assert "<patch_file>" not in workflow
    assert "<patch_files>" not in workflow
    assert "automatic backups" not in workflow


def test_tool_guide_documents_skills_tools_and_rules() -> None:
    guide = get_tool_guide()

    assert "## Skills" in guide
    assert "### list_skills" in guide
    assert "### activate_skill" in guide
    assert "Activated skill content is `CONTEXT`, not `SYSTEM`" in guide
    assert "Do not activate every skill" in guide
