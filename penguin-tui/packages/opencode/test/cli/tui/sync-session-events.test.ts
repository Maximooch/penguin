import { describe, expect, test } from "bun:test"
import type { Session } from "@opencode-ai/sdk/v2"
import { applySessionListEvent } from "../../../src/cli/cmd/tui/context/sync-session-events"

function session(input: { id: string; title: string; created: number; updated: number }): Session {
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
