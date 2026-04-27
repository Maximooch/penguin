from __future__ import annotations

from penguin.prompt_actions import get_tool_guide
from penguin.tools.editing.registry import (
    get_edit_tool_public_names,
    get_edit_tool_schema_map,
    get_patch_operation_types,
)


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


def test_tool_guide_uses_schema_derived_aliases_and_required_fields() -> None:
    guide = get_tool_guide()
    schemas = get_edit_tool_schema_map()

    assert "Required fields: `path`, `content`" in guide
    assert "Required fields: `path`, `operation`" in guide
    assert "Operation types: " in guide

    for tool_name, schema in schemas.items():
        aliases = schema.get("aliases") or []
        if aliases:
            alias_fragment = ", ".join(f"`{alias}`" for alias in aliases)
            assert f"Legacy aliases: {alias_fragment}" in guide

    operation_types_fragment = ", ".join(
        f"`{name}`" for name in get_patch_operation_types()
    )
    assert operation_types_fragment in guide


def test_tool_guide_promotes_canonical_names_over_legacy_headers() -> None:
    guide = get_tool_guide()

    assert "### enhanced_read" not in guide
    assert "### enhanced_write" not in guide
    assert "### apply_diff" not in guide
    assert "### multiedit" not in guide
