import { describe, expect, test } from "bun:test"
import { formatPenguinPromptFailure, recoverPenguinPromptFailure } from "../../../src/cli/cmd/tui/component/prompt/penguin-send"

describe("prompt penguin send", () => {
  test("recovers failed sends by clearing pending state and emitting idle status", () => {
    const state = {
      pending: true,
      pendingSeenBusy: true,
    }
    const events: Array<{
      type: string
      properties: {
        sessionID: string
        status: {
          type: string
        }
      }
    }> = []

    recoverPenguinPromptFailure({
      sessionID: "ses_123",
      clear: () => {
        state.pending = false
        state.pendingSeenBusy = false
      },
      emit: (_type, event) => {
        events.push(event)
      },
    })

    expect(state).toEqual({
      pending: false,
      pendingSeenBusy: false,
    })
    expect(events).toEqual([
      {
        type: "session.status",
        properties: {
          sessionID: "ses_123",
          status: {
            type: "idle",
          },
        },
      },
    ])
  })

  test("formats auth failures with local auth guidance", () => {
    expect(formatPenguinPromptFailure({ status: 401 })).toBe(
      "Failed to send message (401). Check local auth and try again.",
    )
  })

  test("formats non-2xx failures with response details", () => {
    expect(formatPenguinPromptFailure({ status: 500, details: "server exploded" })).toBe(
      "Failed to send message: server exploded",
    )
  })

  test("formats transport failures with connectivity guidance", () => {
    expect(formatPenguinPromptFailure({ error: new Error("network down") })).toBe(
      "Failed to send message: network down. Check local auth/server connectivity and try again.",
    )
  })
})
