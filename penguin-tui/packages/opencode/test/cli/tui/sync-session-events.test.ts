import { describe, expect, test } from "bun:test"
import type { PenguinGoal, PenguinSession } from "../../../src/cli/cmd/tui/context/sync-bootstrap"
import { applySessionListEvent } from "../../../src/cli/cmd/tui/context/sync-session-events"

function session(input: { id: string; title: string; created: number; updated: number }): PenguinSession {
  return {
    id: input.id,
    slug: input.id,
    projectID: "penguin",
    directory: "/tmp/project",
    title: input.title,
    version: "0.0.0",
    time: {
      created: input.created,
      updated: input.updated,
    },
  }
}

function goal(input: Partial<PenguinGoal> = {}): PenguinGoal {
  return {
    id: "goal_1",
    objective: "Ship a robust session goal",
    status: "active",
    revision: 1,
    token_budget: 50_000,
    tokens_used: 0,
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

describe("sync session events", () => {
  test("adds newly created sessions to the cached list", () => {
    const existing = session({ id: "session_a", title: "Existing", created: 100, updated: 100 })
    const created = session({ id: "session_b", title: "Created", created: 200, updated: 200 })

    const next = applySessionListEvent([existing], {
      type: "session.created",
      properties: { info: created },
    })

    expect(next.map((item) => item.id)).toEqual(["session_a", "session_b"])
  })

  test("updates existing sessions without duplicating them", () => {
    const existing = session({ id: "session_a", title: "Before", created: 100, updated: 100 })
    const updated = session({ id: "session_a", title: "After", created: 100, updated: 300 })

    const next = applySessionListEvent([existing], {
      type: "session.updated",
      properties: { info: updated },
    })

    expect(next).toHaveLength(1)
    expect(next[0]?.title).toBe("After")
    expect(next[0]?.time.updated).toBe(300)
  })

  test("replaces goal state from paired session.updated events", () => {
    const existing = {
      ...session({ id: "session_a", title: "Before", created: 100, updated: 100 }),
      goal: goal(),
    }
    const updated = {
      ...session({ id: "session_a", title: "After", created: 100, updated: 300 }),
      goal: goal({ status: "paused", revision: 2, tokens_used: 1_250 }),
    }

    const next = applySessionListEvent([existing], {
      type: "session.updated",
      properties: { info: updated },
    })

    expect(next[0]?.goal).toMatchObject({
      status: "paused",
      revision: 2,
      tokens_used: 1_250,
    })

    const cleared = applySessionListEvent(next, {
      type: "session.updated",
      properties: {
        info: session({ id: "session_a", title: "After", created: 100, updated: 400 }),
      },
    })
    expect(cleared[0]?.goal).toBeUndefined()
  })

  test("removes deleted sessions and leaves unknown deletes untouched", () => {
    const first = session({ id: "session_a", title: "A", created: 100, updated: 100 })
    const second = session({ id: "session_b", title: "B", created: 200, updated: 200 })
    const sessions = [first, second]

    expect(
      applySessionListEvent(sessions, {
        type: "session.deleted",
        properties: { info: { id: "session_a" } },
      }).map((item) => item.id),
    ).toEqual(["session_b"])

    expect(
      applySessionListEvent(sessions, {
        type: "session.deleted",
        properties: { info: { id: "session_missing" } },
      }),
    ).toBe(sessions)
  })

  test("ignores incomplete session list events", () => {
    const sessions = [session({ id: "session_a", title: "A", created: 100, updated: 100 })]

    expect(applySessionListEvent(sessions, { type: "session.created" })).toBe(sessions)
    expect(applySessionListEvent(sessions, { type: "session.updated" })).toBe(sessions)
    expect(applySessionListEvent(sessions, { type: "session.deleted" })).toBe(sessions)
  })
})
