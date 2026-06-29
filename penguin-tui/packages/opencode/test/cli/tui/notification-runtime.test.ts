import { describe, expect, test } from "bun:test"

import {
  attentionEventFromSyncEvent,
  deliverNotificationPayloads,
  notificationEscape,
  notificationEventKey,
  notifyForSyncEvent,
} from "../../../src/cli/cmd/tui/notification-runtime"

describe("terminal notification runtime", () => {
  test("maps approval and question events into attention events", () => {
    expect(
      attentionEventFromSyncEvent({
        type: "permission.asked",
        properties: {
          id: "perm_1",
          sessionID: "ses_1",
          title: "Run shell command",
        },
      }),
    ).toEqual({
      category: "approval_waiting",
      sessionID: "ses_1",
      title: "Penguin needs approval",
      message: "Run shell command",
    })

    expect(
      attentionEventFromSyncEvent({
        type: "question.asked",
        properties: {
          id: "question_1",
          sessionID: "ses_2",
          question: "Continue?",
        },
      }),
    ).toEqual({
      category: "question_waiting",
      sessionID: "ses_2",
      title: "Penguin has a question",
      message: "Continue?",
    })
  })

  test("builds stable duplicate-suppression keys", () => {
    expect(
      notificationEventKey({
        type: "permission.asked",
        properties: {
          id: "perm_1",
          sessionID: "ses_1",
        },
      }),
    ).toBe("permission.asked:ses_1:perm_1")

    expect(notificationEventKey({ type: "session.status", properties: { sessionID: "ses_1" } })).toBeUndefined()
  })

  test("delivers terminal bell and logs non-escape payloads", () => {
    const writes: string[] = []
    const logs: string[] = []

    const delivered = deliverNotificationPayloads(
      [
        {
          channel: "bell",
          category: "approval_waiting",
          title: "Penguin needs approval",
          body: "Approve?",
        },
        {
          channel: "visual",
          category: "question_waiting",
          title: "Penguin has a question",
          body: "Continue?",
        },
      ],
      {
        write: (text) => writes.push(text),
        log: (payload) => logs.push(payload.title),
      },
    )

    expect(delivered).toHaveLength(2)
    expect(writes).toEqual(["\u0007"])
    expect(logs).toEqual(["Penguin has a question"])
  })

  test("sanitizes OSC notification separators", () => {
    expect(
      notificationEscape({
        channel: "osc",
        category: "run_failed",
        title: "Bad;title\u0007",
        body: "Bad;body\u0007",
      }),
    ).toBe("\u001b]9;Bad title ;Bad body \u0007")
  })

  test("notifies only mapped attention events", () => {
    const writes: string[] = []

    expect(
      notifyForSyncEvent(
        {
          type: "message.updated",
          properties: {
            sessionID: "ses_1",
          },
        },
        { mode: "bell" },
        { write: (text) => writes.push(text) },
      ),
    ).toEqual([])

    expect(
      notifyForSyncEvent(
        {
          type: "permission.asked",
          properties: {
            id: "perm_1",
            sessionID: "ses_1",
            reason: "Need shell",
          },
        },
        { mode: "bell" },
        { write: (text) => writes.push(text) },
      ),
    ).toHaveLength(1)
    expect(writes).toEqual(["\u0007"])
  })
})
