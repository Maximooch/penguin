import { describe, expect, test } from "bun:test"
import {
  getPenguinEventDirectory,
  getPenguinEventSessionID,
  normalizePenguinDirectory,
  parsePenguinSessionUsage,
  shouldProcessPenguinEvent,
} from "../../../src/cli/cmd/tui/context/penguin-sync"

describe("penguin sync helpers", () => {
  test("parses top-level and nested session usage payloads", () => {
    expect(
      parsePenguinSessionUsage({
        current_total_tokens: 10,
        max_context_window_tokens: 100,
        available_tokens: 90,
        percentage: 10,
        truncations: {
          total_truncations: 1,
          messages_removed: 2,
          tokens_freed: 30,
        },
      }),
    ).toEqual({
      current_total_tokens: 10,
      max_context_window_tokens: 100,
      available_tokens: 90,
      percentage: 10,
      truncations: {
        total_truncations: 1,
        messages_removed: 2,
        tokens_freed: 30,
      },
    })

    expect(
      parsePenguinSessionUsage({
        usage: {
          current_total_tokens: 25,
          available_tokens: 75,
        },
      }),
    ).toEqual({
      current_total_tokens: 25,
      max_context_window_tokens: null,
      available_tokens: 75,
      percentage: null,
      truncations: {
        total_truncations: 0,
        messages_removed: 0,
        tokens_freed: 0,
      },
    })
  })

  test("extracts session and directory from penguin events", () => {
    const event = {
      type: "message.part.updated",
      properties: {
        info: {
          session_id: "ses_123",
          path: {
            cwd: "/tmp/project",
          },
        },
      },
    }

    expect(getPenguinEventSessionID(event)).toBe("ses_123")
    expect(getPenguinEventDirectory(event)).toBe("/tmp/project")
  })

  test("filters out cross-directory events when no active session is open", () => {
    const keep = shouldProcessPenguinEvent({
      event: {
        type: "message.updated",
        properties: {
          sessionID: "ses_a",
          directory: "/workspace/app",
        },
      },
      appDirectory: normalizePenguinDirectory("/workspace/app"),
      sessionDirectory: (sessionID) => (sessionID === "ses_a" ? normalizePenguinDirectory("/workspace/app") : undefined),
    })
    const drop = shouldProcessPenguinEvent({
      event: {
        type: "message.updated",
        properties: {
          sessionID: "ses_b",
          directory: "/workspace/other",
        },
      },
      appDirectory: normalizePenguinDirectory("/workspace/app"),
      sessionDirectory: (sessionID) =>
        sessionID === "ses_b" ? normalizePenguinDirectory("/workspace/other") : undefined,
    })

    expect(keep).toBe(true)
    expect(drop).toBe(false)
  })

  test("filters directoryless system events outside an active session scope", () => {
    const result = shouldProcessPenguinEvent({
      event: {
        type: "lsp.updated",
        properties: {},
      },
      activeSessionID: "ses_123",
      appDirectory: normalizePenguinDirectory("/workspace/app"),
      sessionDirectory: () => normalizePenguinDirectory("/workspace/app"),
    })

    expect(result).toBe(false)
  })
})
