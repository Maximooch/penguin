import { describe, expect, test } from "bun:test"
import { deriveInlineToolState, isDeniedInlineToolError } from "../../../src/cli/cmd/tui/routes/session/inline-tool-row"

describe("inline tool row state", () => {
  test("treats permission denials as denied instead of expandable failures", () => {
    expect(isDeniedInlineToolError("user dismissed permission prompt")).toBe(true)
    expect(isDeniedInlineToolError("User Dismissed permission prompt")).toBe(true)
    expect(deriveInlineToolState({ error: "user dismissed permission prompt" })).toEqual({
      denied: true,
      failed: false,
      clickable: false,
    })
  })

  test("treats tool errors as expandable failures", () => {
    expect(deriveInlineToolState({ error: "Command failed with exit code 1" })).toEqual({
      denied: false,
      failed: true,
      clickable: true,
    })
  })

  test("keeps successful rows non-clickable unless a caller adds an action", () => {
    expect(deriveInlineToolState({})).toEqual({
      denied: false,
      failed: false,
      clickable: false,
    })
    expect(deriveInlineToolState({ onClick: true })).toEqual({
      denied: false,
      failed: false,
      clickable: true,
    })
  })
})
