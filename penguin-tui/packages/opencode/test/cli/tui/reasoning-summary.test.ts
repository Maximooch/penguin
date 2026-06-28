import { describe, expect, test } from "bun:test"

import { formatPart } from "../../../src/cli/cmd/tui/util/transcript"
import {
  formatReasoningHeader,
  formatReasoningLabel,
  isReasoningComplete,
  parseReasoningSummary,
} from "../../../src/cli/cmd/tui/util/reasoning-summary"

describe("reasoning summary display", () => {
  test("keeps ordinary reasoning as body-only content", () => {
    expect(parseReasoningSummary("Let me think...")).toEqual({
      title: null,
      body: "Let me think...",
    })
    expect(formatReasoningHeader(null)).toBe("_Thinking:_")
    expect(formatReasoningLabel(null, false)).toBe("Thinking")
    expect(formatReasoningLabel(null, true)).toBe("Thought")
  })

  test("splits a bold summary title from markdown body", () => {
    expect(parseReasoningSummary("**Inspecting workflow**\n\nChecking files...")).toEqual({
      title: "Inspecting workflow",
      body: "Checking files...",
    })
    expect(formatReasoningHeader("Inspecting workflow")).toBe("_Thinking: Inspecting workflow_")
    expect(formatReasoningLabel("Inspecting workflow", false)).toBe("Thinking: Inspecting workflow")
    expect(formatReasoningLabel("Inspecting workflow", true)).toBe("Thought: Inspecting workflow")
  })

  test("handles a complete title while body is still streaming", () => {
    expect(parseReasoningSummary("**Inspecting workflow**")).toEqual({
      title: "Inspecting workflow",
      body: "",
    })
  })

  test("exports summary titles separately from reasoning body", () => {
    const result = formatPart(
      {
        id: "part-1",
        messageID: "msg-1",
        sessionID: "session-1",
        type: "reasoning",
        text: "**Inspecting workflow**\n\nChecking files...",
        time: { start: 1 },
      },
      { thinking: true, toolDetails: true, assistantMetadata: true },
    )

    expect(result).toBe("_Thinking: Inspecting workflow_\n\nChecking files...\n\n")
  })

  test("treats missing reasoning time metadata as unfinished", () => {
    expect(
      isReasoningComplete({
        part: {},
        message: { time: {} },
      }),
    ).toBe(false)
    expect(
      isReasoningComplete({
        part: { time: { end: 2 } },
        message: { time: {} },
      }),
    ).toBe(true)
    expect(
      isReasoningComplete({
        part: {},
        message: { time: { completed: 3 } },
      }),
    ).toBe(true)
  })
})
