import { describe, expect, test } from "bun:test"
import type { Session } from "@opencode-ai/sdk/v2"
import { removeSessionRecord, upsertSessionRecord } from "../../../src/cli/cmd/tui/util/session-family"

function session(input: { id: string; title: string; created: number; updated: number; parentID?: string }): Session {
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
    ...(input.parentID ? { parentID: input.parentID } : {}),
  }
}

describe("sync session store", () => {
  test("upserts existing sessions without relying on sorted arrays", () => {
    const root = session({ id: "ses_root", title: "Root", created: 100, updated: 100 })
    const childB = session({
      id: "ses_child_b",
      title: "Child B",
      parentID: "ses_root",
      created: 120,
      updated: 120,
    })
    const childA = session({
      id: "ses_child_a",
      title: "Child A",
      parentID: "ses_root",
      created: 110,
      updated: 110,
    })

    const updated = upsertSessionRecord([root, childB, childA], {
      ...childA,
      title: "Child A Updated",
      time: { ...childA.time, updated: 210 },
    })

    expect(updated.map((item) => item.id)).toEqual(["ses_root", "ses_child_b", "ses_child_a"])
    expect(updated[2]?.title).toBe("Child A Updated")
  })

  test("appends newly created child sessions to unsorted stores", () => {
    const root = session({ id: "ses_root", title: "Root", created: 100, updated: 100 })
    const child = session({
      id: "ses_child_a",
      title: "Child A",
      parentID: "ses_root",
      created: 110,
      updated: 110,
    })
    const created = session({
      id: "ses_child_b",
      title: "Child B",
      parentID: "ses_root",
      created: 120,
      updated: 120,
    })

    const updated = upsertSessionRecord([root, child], created)

    expect(updated.map((item) => item.id)).toEqual(["ses_root", "ses_child_a", "ses_child_b"])
  })

  test("removes only the requested child session", () => {
    const root = session({ id: "ses_root", title: "Root", created: 100, updated: 100 })
    const childA = session({
      id: "ses_child_a",
      title: "Child A",
      parentID: "ses_root",
      created: 110,
      updated: 110,
    })
    const childB = session({
      id: "ses_child_b",
      title: "Child B",
      parentID: "ses_root",
      created: 120,
      updated: 120,
    })

    const updated = removeSessionRecord([root, childA, childB], childA.id)

    expect(updated.map((item) => item.id)).toEqual(["ses_root", "ses_child_b"])
  })
})
