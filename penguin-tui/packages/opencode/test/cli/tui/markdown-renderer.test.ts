import { describe, expect, test } from "bun:test"
import { shouldUseOpenCodeMarkdownRenderer } from "../../../src/cli/cmd/tui/util/markdown-renderer"

describe("markdown renderer policy", () => {
  test("uses OpenCode markdown by default", () => {
    expect(shouldUseOpenCodeMarkdownRenderer(undefined)).toBe(true)
  })

  test("keeps legacy truthy opt-in values enabled", () => {
    expect(shouldUseOpenCodeMarkdownRenderer("1")).toBe(true)
    expect(shouldUseOpenCodeMarkdownRenderer("true")).toBe(true)
  })

  test("allows explicit opt-out values", () => {
    expect(shouldUseOpenCodeMarkdownRenderer("0")).toBe(false)
    expect(shouldUseOpenCodeMarkdownRenderer("false")).toBe(false)
    expect(shouldUseOpenCodeMarkdownRenderer("off")).toBe(false)
    expect(shouldUseOpenCodeMarkdownRenderer("no")).toBe(false)
  })
})
