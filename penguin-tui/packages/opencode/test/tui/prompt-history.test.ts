import { describe, expect, test } from "bun:test"
import {
  appendPromptHistory,
  movePromptHistory,
  normalizePromptHistory,
  parsePromptHistoryLine,
  type PromptHistoryBrowseState,
  type PromptInfo,
} from "../../src/cli/cmd/tui/component/prompt/history-state"

function prompt(input: string, mode?: PromptInfo["mode"]): PromptInfo {
  return {
    input,
    mode,
    parts: [],
  }
}

describe("prompt history", () => {
  test("normalizes blank and adjacent duplicate entries", () => {
    expect(normalizePromptHistory([prompt("   "), prompt("one"), prompt("one"), prompt("two"), prompt("one")])).toEqual(
      [prompt("one"), prompt("two"), prompt("one")],
    )
  })

  test("does not append blank or duplicate adjacent entries", () => {
    const base = [prompt("one")]

    expect(appendPromptHistory(base, prompt("   "))).toBe(base)
    expect(appendPromptHistory(base, prompt("one"))).toBe(base)
    expect(appendPromptHistory(base, prompt("two"))).toEqual([prompt("one"), prompt("two")])
  })

  test("moves through history and restores the draft", () => {
    const state: PromptHistoryBrowseState = {
      draft: prompt(""),
      history: [prompt("one"), prompt("two")],
      index: null,
    }

    const latest = movePromptHistory(state, -1, prompt("draft"))
    expect(latest.prompt).toEqual(prompt("two"))

    const older = movePromptHistory(latest.state, -1, prompt("two"))
    expect(older.prompt).toEqual(prompt("one"))

    const newer = movePromptHistory(older.state, 1, prompt("one"))
    expect(newer.prompt).toEqual(prompt("two"))

    const draft = movePromptHistory(newer.state, 1, prompt("two"))
    expect(draft.prompt).toEqual(prompt("draft"))
    expect(draft.state.index).toBeNull()
  })

  test("preserves draft prompt parts while browsing", () => {
    const draftPrompt: PromptInfo = {
      input: "@agent draft",
      parts: [
        {
          type: "agent",
          name: "planner",
          source: {
            start: 0,
            end: 6,
            value: "@agent",
          },
        },
      ],
    }
    const state: PromptHistoryBrowseState = {
      draft: prompt(""),
      history: [prompt("one")],
      index: null,
    }

    const latest = movePromptHistory(state, -1, draftPrompt)
    const restored = movePromptHistory(latest.state, 1, prompt("one"))

    expect(restored.prompt).toEqual(draftPrompt)
  })

  test("rejects malformed prompt history rows before normalization", () => {
    expect(parsePromptHistoryLine(JSON.stringify({ input: "valid", parts: [] }))).toEqual(prompt("valid"))
    expect(parsePromptHistoryLine(JSON.stringify({ input: 123, parts: [] }))).toBeNull()
    expect(parsePromptHistoryLine(JSON.stringify({ input: "missing parts" }))).toBeNull()
    expect(parsePromptHistoryLine(JSON.stringify({ input: "bad part", parts: [{ type: "unknown" }] }))).toBeNull()
    expect(parsePromptHistoryLine(JSON.stringify({ input: "bad agent", parts: [{ type: "agent" }] }))).toBeNull()
    expect(
      parsePromptHistoryLine(
        JSON.stringify({
          input: "bad text source",
          parts: [{ type: "text", text: "full paste", source: {} }],
        }),
      ),
    ).toBeNull()
    expect(
      parsePromptHistoryLine(
        JSON.stringify({
          input: "[Pasted]",
          parts: [
            {
              type: "text",
              text: "full paste",
              source: {
                text: {
                  start: 0,
                  end: 8,
                  value: "[Pasted]",
                },
              },
            },
          ],
        }),
      ),
    ).toEqual({
      input: "[Pasted]",
      parts: [
        {
          type: "text",
          text: "full paste",
          source: {
            text: {
              start: 0,
              end: 8,
              value: "[Pasted]",
            },
          },
        },
      ],
    })
    expect(parsePromptHistoryLine("{not-json")).toBeNull()
  })
})
