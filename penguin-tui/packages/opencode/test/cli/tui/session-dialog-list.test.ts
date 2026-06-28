import { describe, expect, test } from "bun:test"
import type { PenguinSession } from "../../../src/cli/cmd/tui/context/sync-bootstrap"
import {
  appendSessionIfMissing,
  formatSessionDirectoryLabel,
  getDialogSessions,
  isBlankPenguinSession,
} from "../../../src/cli/cmd/tui/util/session-dialog-list"

function session(input: {
  id: string
  title: string
  updated: number
  displayMessageCount?: number
  fallbackTitle?: boolean
  parentID?: string
}): PenguinSession {
  return {
    id: input.id,
    slug: input.id,
    projectID: "penguin",
    directory: "/tmp/project",
    title: input.title,
    version: "0.0.0",
    time: {
      created: input.updated - 10,
      updated: input.updated,
    },
    display_message_count: input.displayMessageCount,
    fallback_title: input.fallbackTitle,
    ...(input.parentID ? { parentID: input.parentID } : {}),
  }
}

describe("Penguin dialog session list", () => {
  test("filters blank fallback sessions without hiding meaningful sessions", () => {
    const blank = session({
      displayMessageCount: 0,
      fallbackTitle: true,
      id: "session_blank",
      title: "Session _blank",
      updated: 300,
    })
    const titled = session({
      displayMessageCount: 0,
      fallbackTitle: false,
      id: "session_titled",
      title: "PM System Notes",
      updated: 200,
    })
    const hasDisplayMessages = session({
      displayMessageCount: 1,
      fallbackTitle: true,
      id: "session_message",
      title: "Session message",
      updated: 100,
    })

    expect(isBlankPenguinSession(blank)).toBe(true)
    expect(isBlankPenguinSession(titled)).toBe(false)
    expect(isBlankPenguinSession(hasDisplayMessages)).toBe(false)

    expect(
      getDialogSessions({
        cachedSessions: [blank, titled, hasDisplayMessages],
        penguin: true,
        searchQuery: "",
      }).map((item) => item.id),
    ).toEqual(["session_titled", "session_message"])
  })

  test("keeps the active session visible even when it is a blank fallback", () => {
    const active = session({
      displayMessageCount: 0,
      fallbackTitle: true,
      id: "session_active",
      title: "Session active",
      updated: 100,
    })

    expect(
      getDialogSessions({
        activeSessionID: active.id,
        cachedSessions: [active],
        penguin: true,
        searchQuery: "",
      }).map((item) => item.id),
    ).toEqual([active.id])
  })

  test("appends the active cached session when the Penguin refresh result is missing it", () => {
    const active = session({
      displayMessageCount: 1,
      fallbackTitle: false,
      id: "session_active",
      title: "Current",
      updated: 100,
    })

    expect(appendSessionIfMissing([], active)).toEqual([active])
    expect(
      getDialogSessions({
        activeSessionID: active.id,
        cachedSessions: [active],
        penguin: true,
        searchQuery: "",
        searchResults: [],
      }).map((item) => item.id),
    ).toEqual([active.id])
  })

  test("does not append the active session while the user is searching", () => {
    const active = session({
      displayMessageCount: 1,
      fallbackTitle: false,
      id: "session_active",
      title: "Current",
      updated: 100,
    })

    expect(
      getDialogSessions({
        activeSessionID: active.id,
        cachedSessions: [active],
        penguin: true,
        searchQuery: "missing",
        searchResults: [],
      }),
    ).toEqual([])
  })

  test("omits directory labels for sessions in the current directory", () => {
    expect(
      formatSessionDirectoryLabel({
        currentDirectory: "/tmp/project",
        sessionDirectory: "/tmp/project/",
      }),
    ).toBeUndefined()
  })

  test("shows truncated directory labels for copied sessions", () => {
    expect(
      formatSessionDirectoryLabel({
        currentDirectory: "/tmp/project",
        sessionDirectory: "/tmp/project-feature-branch-with-long-name",
        maxLength: 20,
      }),
    ).toBe("project-feature-bra…")
  })

  test("shows directory labels when the current directory is not available", () => {
    expect(
      formatSessionDirectoryLabel({
        sessionDirectory: "/tmp/attached-project",
      }),
    ).toBe("attached-project")
  })
})
