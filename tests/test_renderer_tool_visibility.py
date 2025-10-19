from rich.console import Console

from penguin.cli.renderer import UnifiedRenderer


def test_renderer_strips_tool_results_when_disabled() -> None:
    renderer = UnifiedRenderer(console=Console(), show_tool_results=False)
    content = "Before\n<list_files_filtered>data</list_files_filtered>\nAfter"

    filtered = renderer.filter_content(content)

    assert "data" not in filtered
    assert "<list_files_filtered>" not in filtered
    assert "Before" in filtered
    assert "After" in filtered


def test_renderer_preserves_tool_results_when_enabled() -> None:
    renderer = UnifiedRenderer(console=Console(), show_tool_results=True)
    content = "Before\n<list_files_filtered>data</list_files_filtered>\nAfter"

    filtered = renderer.filter_content(content)

    # When tool results are visible, content should remain intact
    assert "data" in filtered
    assert "<list_files_filtered>" in filtered
