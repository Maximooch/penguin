import { describe, expect, test } from "bun:test"
import {
  assistantDurationMs,
  isAssistantSettled,
  type DurationMessage,
} from "../../src/cli/cmd/tui/routes/session/message-duration"

describe("session message duration", () => {
  test("treats completed Penguin assistant messages as settled without finish", () => {
    const message: DurationMessage = {
      id: "msg_assistant",
      parentID: "msg_user",
      role: "assistant",
      time: {
        created: 11_500,
        completed: 12_300,
      },
    }

    expect(isAssistantSettled(message)).toBe(true)
    expect(
      assistantDurationMs(message, [
        {
          id: "msg_user",
          role: "user",
          time: {
            created: 10_000,
          },
        },
        message,
      ]),
    ).toBe(2_300)
  })

  test("keeps OpenCode finish semantics for assistant messages without completed time", () => {
    expect(
      isAssistantSettled({
        finish: "stop",
        id: "msg_assistant",
        parentID: "msg_user",
        role: "assistant",
        time: {
          created: 10_000,
        },
      }),
    ).toBe(true)
    expect(
      isAssistantSettled({
        finish: "tool-calls",
        id: "msg_assistant",
        parentID: "msg_user",
        role: "assistant",
        time: {
          created: 10_000,
        },
      }),
    ).toBe(false)
  })

  test("falls back to the previous user when parent id is missing or root", () => {
    const message: DurationMessage = {
      id: "msg_assistant",
      parentID: "root",
      role: "assistant",
      time: {
        created: 11_000,
        completed: 15_500,
      },
    }

    expect(
      assistantDurationMs(message, [
        {
          id: "msg_user_1",
          role: "user",
          time: {
            created: 1_000,
          },
        },
        {
          id: "msg_user_2",
          role: "user",
          time: {
            created: 10_000,
          },
        },
        message,
      ]),
    ).toBe(5_500)
  })

  test("does not report duration for unfinished assistant messages", () => {
    const message: DurationMessage = {
      id: "msg_assistant",
      parentID: "msg_user",
      role: "assistant",
      time: {
        created: 11_000,
      },
    }

    expect(assistantDurationMs(message, [])).toBe(0)
  })
})
