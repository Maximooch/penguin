import { describe, expect, test } from "bun:test"

import { formatMcpResourceAutocomplete } from "../../../src/cli/cmd/tui/component/prompt/mcp-autocomplete"

describe("MCP resource autocomplete", () => {
  test("uses resource name as both display source and fuzzy-match value", () => {
    const option = formatMcpResourceAutocomplete(
      {
        name: "Project notes",
        uri: "file:///very/noisy/path/project-notes.md",
      },
      40,
    )

    expect(option).toEqual({
      display: "Project notes",
      value: "Project notes",
    })
  })

  test("does not leak URI text into truncated display labels", () => {
    const option = formatMcpResourceAutocomplete(
      {
        name: "Very long project notes resource name",
        uri: "file:///very/noisy/path/project-notes.md",
      },
      18,
    )

    expect(option.display).not.toContain("file://")
    expect(option.value).toBe("Very long project notes resource name")
  })
})
