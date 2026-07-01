import { describe, expect, test } from "bun:test"
import { fileAutocompleteURL } from "../../../src/cli/cmd/tui/component/prompt/file-url"

describe("file autocomplete urls", () => {
  test("builds file urls from the scoped search directory", () => {
    expect(fileAutocompleteURL({ baseDirectory: "/workspace/session-b", item: "src/app.ts" })).toBe(
      "file:///workspace/session-b/src/app.ts",
    )
  })

  test("preserves line-range query params for selected files", () => {
    expect(
      fileAutocompleteURL({
        baseDirectory: "/workspace/session-b",
        item: "src/app.ts",
        lineRange: { startLine: 3, endLine: 8 },
      }),
    ).toBe("file:///workspace/session-b/src/app.ts?start=3&end=8")
  })
})
