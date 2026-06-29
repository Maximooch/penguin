import { describe, expect, test } from "bun:test"
import {
  formatSubagentTaskDescription,
  formatSubagentTaskLabel,
  formatSubagentToolcalls,
  isBackgroundSubagentTask,
} from "../../../src/cli/cmd/tui/routes/session/subagent-task"

describe("subagent task display", () => {
  test("keeps background marker with the subagent label", () => {
    expect(formatSubagentTaskLabel({ subagentType: "review", background: true })).toBe("Review Task (background)")
  })

  test("formats unknown subagent labels", () => {
    expect(formatSubagentTaskLabel({})).toBe("Unknown Task")
  })

  test("formats toolcall counts", () => {
    expect(formatSubagentToolcalls(1)).toBe("1 toolcall")
    expect(formatSubagentToolcalls(2)).toBe("2 toolcalls")
  })

  test("adds toolcall details to descriptions", () => {
    expect(formatSubagentTaskDescription({ description: "Check auth", toolcalls: 3 })).toBe("Check auth (3 toolcalls)")
  })

  test("detects optional background metadata without requiring it in the typed contract", () => {
    expect(isBackgroundSubagentTask({ background: true })).toBe(true)
    expect(isBackgroundSubagentTask({ background: false })).toBe(false)
    expect(isBackgroundSubagentTask(undefined)).toBe(false)
  })
})
