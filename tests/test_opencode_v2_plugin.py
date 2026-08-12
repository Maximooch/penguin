"""Boundary checks for Penguin's native OpenCode 2 TUI extension."""

from pathlib import Path

PLUGIN = (
    Path(__file__).parents[1] / "penguin-tui-v2" / "plugins" / "tui" / "penguin.tsx"
)


def test_v2_extension_uses_only_the_native_tui_plugin_seam() -> None:
    source = PLUGIN.read_text(encoding="utf-8")

    assert 'import type { Plugin } from "@opencode-ai/plugin/tui"' in source
    assert "context: Plugin.Context" in source
    assert 'id: "penguin.product"' in source
    assert 'id: "penguin.status"' in source
    assert 'context.ui.slot("app"' in source

    forbidden_transport = (
        "fetch(",
        "axios",
        "/api/",
        "OPENCODE_PASSWORD",
        "PENGUIN_LOCAL_AUTH_TOKEN",
        "react/jsx",
        "@opentui/solid",
    )
    assert all(token not in source for token in forbidden_transport)
