import { describe, expect, test } from "bun:test"
import type { Session } from "@opencode-ai/sdk/v2"
import { getSessionFamily } from "../../../src/cli/cmd/tui/util/session-family"

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

describe("session family navigation", () => {
  test("returns the full parent-child family from a child session", () => {
    const parent = session({
      id: "ses_parent",
      title: "Parent",
      created: 100,
      updated: 300,
    })
    const childA = session({
      id: "ses_child_a",
      title: "Child A",
      parentID: parent.id,
      created: 110,
      updated: 310,
    })
    const childB = session({
      id: "ses_child_b",
      title: "Child B",
      parentID: parent.id,
      created: 120,
      updated: 320,
    })
    const other = session({
      id: "ses_other",
      title: "Other",
      created: 130,
      updated: 330,
    })

    const family = getSessionFamily([childB, other, parent, childA], childB.id)

    expect(family.map((item) => item.id)).toEqual(["ses_parent", "ses_child_a", "ses_child_b"])
  })

  test("uses the same family ordering when navigating from the parent session", () => {
    const parent = session({
      id: "ses_parent",
      title: "Parent",
      created: 100,
      updated: 300,
    })
    const childA = session({
      id: "ses_child_a",
      title: "Child A",
      parentID: parent.id,
      created: 115,
      updated: 315,
    })
    const childB = session({
      id: "ses_child_b",
      title: "Child B",
      parentID: parent.id,
      created: 120,
      updated: 320,
    })

    const family = getSessionFamily([childB, parent, childA], parent.id)

    expect(family.map((item) => item.id)).toEqual(["ses_parent", "ses_child_a", "ses_child_b"])
  })

  test("returns an empty family for unknown sessions", () => {
    const parent = session({
      id: "ses_parent",
      title: "Parent",
      created: 100,
      updated: 300,
    })

    expect(getSessionFamily([parent], "ses_missing")).toEqual([])
  })
})
