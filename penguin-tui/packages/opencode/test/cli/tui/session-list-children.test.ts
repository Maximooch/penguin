import { describe, expect, test } from "bun:test"
import type { Session } from "@opencode-ai/sdk/v2"
import {
  expandSessionSearchResults,
  formatSessionListTitle,
  getSessionListEntries,
} from "../../../src/cli/cmd/tui/util/session-family"

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

describe("session list children", () => {
  test("groups child sessions under the parent using family recency", () => {
    const parent = session({
      id: "ses_parent",
      title: "Parent",
      created: 100,
      updated: 200,
    })
    const child = session({
      id: "ses_child",
      title: "Child",
      parentID: parent.id,
      created: 110,
      updated: 500,
    })
    const other = session({
      id: "ses_other",
      title: "Other Root",
      created: 120,
      updated: 300,
    })

    const entries = getSessionListEntries([other, child, parent])

    expect(entries.map((item) => item.session.id)).toEqual(["ses_parent", "ses_child", "ses_other"])
    expect(entries.map((item) => item.depth)).toEqual([0, 1, 0])
    expect(entries[1]?.parent?.id).toBe("ses_parent")
  })

  test("includes cached parent context when search returns only a child session", () => {
    const parent = session({
      id: "ses_parent",
      title: "Parent",
      created: 100,
      updated: 200,
    })
    const child = session({
      id: "ses_child",
      title: "Child",
      parentID: parent.id,
      created: 110,
      updated: 210,
    })
    const merged = expandSessionSearchResults([child], [parent, child])
    const entries = getSessionListEntries(merged)

    expect(entries.map((item) => item.session.id)).toEqual(["ses_parent", "ses_child"])
    expect(entries.map((item) => item.depth)).toEqual([0, 1])
  })

  test("keeps orphaned child sessions indented instead of promoting them to roots", () => {
    const child = session({
      id: "ses_child",
      title: "Child",
      parentID: "ses_parent",
      created: 110,
      updated: 210,
    })
    const entries = getSessionListEntries([child])

    expect(entries).toHaveLength(1)
    expect(entries[0]?.familyID).toBe("ses_parent")
    expect(entries[0]?.depth).toBe(1)
    expect(formatSessionListTitle(entries[0]!.session.title, entries[0]!.depth)).toBe("  > Child")
  })
})
