import { describe, expect, test } from "bun:test"
import type { PenguinGoal } from "../../../src/cli/cmd/tui/context/sync-bootstrap"
import { summarizeSessionGoal } from "../../../src/cli/cmd/tui/routes/session/goal-summary"

function goal(input: Partial<PenguinGoal> = {}): PenguinGoal {
  return {
    id: "goal_1",
    objective: "Ship a robust session goal",
    status: "active",
    revision: 1,
    token_budget: 50_000,
    tokens_used: 1_250,
    time_used_seconds: 0,
    created_at: "2026-07-09T12:00:00+00:00",
    updated_at: "2026-07-09T12:00:00+00:00",
    active_run_id: null,
    active_run_owner: null,
    active_run_started_at: null,
    last_run_id: null,
    last_result: null,
    metadata: {},
    ...input,
  }
}

describe("session goal summary", () => {
  test("formats status, objective, and budget progress", () => {
    expect(summarizeSessionGoal(goal({ status: "budget_limited" }))).toEqual({
      status: "budget limited",
      objective: "Ship a robust session goal",
      tokens: "1,250 / 50,000 tokens",
    })
  })

  test("describes token usage when the goal has no budget", () => {
    expect(summarizeSessionGoal(goal({ token_budget: null }))).toMatchObject({
      tokens: "1,250 tokens used",
    })
  })

  test("clamps multiline objectives to a single sidebar preview", () => {
    const summary = summarizeSessionGoal(
      goal({
        objective: `First line\n${"very long objective ".repeat(12)}`,
      }),
    )

    expect(summary.objective).not.toContain("\n")
    expect(summary.objective.length).toBeLessThanOrEqual(120)
    expect(summary.objective.endsWith("…")).toBe(true)
  })
})
