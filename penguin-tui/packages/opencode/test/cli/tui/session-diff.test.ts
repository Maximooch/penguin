import { describe, expect, test } from "bun:test"
import { normalizeSessionDiff } from "../../../src/cli/cmd/tui/context/session-diff"

describe("session diff contract", () => {
  test("rejects malformed diff payloads", () => {
    expect(normalizeSessionDiff(undefined)).toEqual([])
    expect(normalizeSessionDiff({ file: "src/app.ts" })).toEqual([])
    expect(
      normalizeSessionDiff([null, {}, { file: "" }, { file: "src/app.ts", additions: "1", deletions: -1 }]),
    ).toEqual([
      {
        file: "src/app.ts",
        before: "",
        after: "",
        additions: 0,
        deletions: 0,
      },
    ])
  })

  test("sorts and merges duplicate file rows", () => {
    expect(
      normalizeSessionDiff([
        {
          file: "src/b.ts",
          before: "",
          after: "first",
          additions: 1,
          deletions: 0,
        },
        {
          file: "src/a.ts",
          before: "old",
          after: "new",
          additions: 2,
          deletions: 1,
        },
        {
          file: "src/b.ts",
          before: "older",
          after: "second",
          additions: 3,
          deletions: 2,
        },
      ]),
    ).toEqual([
      {
        file: "src/a.ts",
        before: "old",
        after: "new",
        additions: 2,
        deletions: 1,
      },
      {
        file: "src/b.ts",
        before: "older",
        after: "second",
        additions: 4,
        deletions: 2,
      },
    ])
  })
})
