import { describe, expect, test } from "bun:test"

import { inlineFileReferenceParts } from "../../../src/cli/cmd/tui/component/prompt/inline-file-references"

describe("inline file references", () => {
  test("creates file parts for manually typed @file references", () => {
    expect(
      inlineFileReferenceParts({
        text: "please inspect @AGENTS.md and @src/main.py",
        directory: "/workspace/project",
      }),
    ).toEqual([
      {
        type: "file",
        mime: "text/plain",
        filename: "AGENTS.md",
        url: "file:///workspace/project/AGENTS.md",
        source: {
          type: "file",
          path: "AGENTS.md",
          text: {
            start: 15,
            end: 25,
            value: "@AGENTS.md",
          },
        },
      },
      {
        type: "file",
        mime: "text/plain",
        filename: "src/main.py",
        url: "file:///workspace/project/src/main.py",
        source: {
          type: "file",
          path: "src/main.py",
          text: {
            start: 30,
            end: 42,
            value: "@src/main.py",
          },
        },
      },
    ])
  })

  test("deduplicates existing autocomplete-selected file parts", () => {
    expect(
      inlineFileReferenceParts({
        text: "see @AGENTS.md",
        directory: "/workspace/project",
        existingParts: [
          {
            type: "file",
            url: "file:///workspace/project/AGENTS.md",
            source: { type: "file", path: "AGENTS.md" },
          },
        ],
      }),
    ).toEqual([])
  })

  test("ignores bare agent-style mentions without file extensions", () => {
    expect(
      inlineFileReferenceParts({
        text: "@build check @README.md",
        directory: "/workspace/project",
      }).map((part) => part.filename),
    ).toEqual(["README.md"])
  })

  test("ignores dotted decorator-style prompt text", () => {
    expect(
      inlineFileReferenceParts({
        text: "add @pytest.fixture and @app.route('/health') decorators near @README.md",
        directory: "/workspace/project",
      }).map((part) => part.filename),
    ).toEqual(["README.md"])
  })

  test("deduplicates references that resolve to the same file URL", () => {
    expect(
      inlineFileReferenceParts({
        text: "compare @README.md with @./README.md",
        directory: "/workspace/project",
      }).map((part) => part.filename),
    ).toEqual(["README.md"])
  })
})
