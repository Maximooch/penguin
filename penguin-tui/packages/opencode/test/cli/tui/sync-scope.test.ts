import { describe, expect, test } from "bun:test"
import {
  extractSyncEventDirectory,
  extractSyncEventSessionID,
  normalizeSyncDirectory,
  shouldIgnorePenguinScopedEvent,
} from "../../../src/cli/cmd/tui/context/sync-scope"

const project = normalizeSyncDirectory("/__penguin_sync_scope_project")!
const other = normalizeSyncDirectory("/__penguin_sync_scope_other")!

describe("sync scope helpers", () => {
  test("extracts session ids from supported Penguin event shapes", () => {
    expect(extractSyncEventSessionID({ properties: { sessionID: "ses_direct" } })).toBe("ses_direct")
    expect(extractSyncEventSessionID({ properties: { session_id: "ses_snake" } })).toBe("ses_snake")
    expect(extractSyncEventSessionID({ properties: { conversation_id: "ses_conv" } })).toBe("ses_conv")
    expect(extractSyncEventSessionID({ properties: { info: { sessionID: "ses_info" } } })).toBe("ses_info")
    expect(extractSyncEventSessionID({ properties: { part: { sessionID: "ses_part" } } })).toBe("ses_part")
    expect(extractSyncEventSessionID({ properties: {} })).toBeUndefined()
  })

  test("extracts directories from supported Penguin event shapes", () => {
    expect(extractSyncEventDirectory({ properties: { directory: project } })).toBe(project)
    expect(extractSyncEventDirectory({ properties: { info: { directory: project } } })).toBe(project)
    expect(extractSyncEventDirectory({ properties: { info: { path: { cwd: project } } } })).toBe(project)
    expect(extractSyncEventDirectory({ properties: { path: { cwd: project } } })).toBe(project)
    expect(extractSyncEventDirectory({ properties: { part: { directory: project } } })).toBe(project)
    expect(extractSyncEventDirectory({ properties: {} })).toBeUndefined()
  })

  test("keeps active-session events scoped to the current session", () => {
    const sessionDirectory = (sessionID?: string) => (sessionID === "ses_active" ? project : other)

    expect(
      shouldIgnorePenguinScopedEvent({
        activeSessionID: "ses_active",
        appDirectory: project,
        event: { type: "message.updated", properties: { sessionID: "ses_active" } },
        sessionDirectory,
      }),
    ).toBe(false)

    expect(
      shouldIgnorePenguinScopedEvent({
        activeSessionID: "ses_active",
        appDirectory: project,
        event: { type: "message.updated", properties: { sessionID: "ses_other" } },
        sessionDirectory,
      }),
    ).toBe(true)
  })

  test("filters unscoped directory events while inside a session", () => {
    const sessionDirectory = () => project

    expect(
      shouldIgnorePenguinScopedEvent({
        activeSessionID: "ses_active",
        appDirectory: project,
        event: { type: "message.updated", properties: { directory: other } },
        sessionDirectory,
      }),
    ).toBe(true)

    expect(
      shouldIgnorePenguinScopedEvent({
        activeSessionID: "ses_active",
        appDirectory: project,
        event: { type: "lsp.updated", properties: {} },
        sessionDirectory,
      }),
    ).toBe(true)
  })

  test("filters session-scoped events outside the current directory", () => {
    const sessionDirectory = (sessionID?: string) => (sessionID === "ses_other" ? other : undefined)

    expect(
      shouldIgnorePenguinScopedEvent({
        appDirectory: project,
        event: { type: "message.updated", properties: { sessionID: "ses_other" } },
        sessionDirectory,
      }),
    ).toBe(true)

    expect(
      shouldIgnorePenguinScopedEvent({
        appDirectory: project,
        event: { type: "message.updated", properties: { sessionID: "ses_unknown", directory: other } },
        sessionDirectory,
      }),
    ).toBe(true)
  })

  test("keeps matching directory-scoped events outside a session", () => {
    expect(
      shouldIgnorePenguinScopedEvent({
        appDirectory: project,
        event: { type: "lsp.updated", properties: { directory: project } },
        sessionDirectory: () => undefined,
      }),
    ).toBe(false)

    expect(
      shouldIgnorePenguinScopedEvent({
        appDirectory: project,
        event: { type: "lsp.updated", properties: {} },
        sessionDirectory: () => undefined,
      }),
    ).toBe(true)
  })
})
