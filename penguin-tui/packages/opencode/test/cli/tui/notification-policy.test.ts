import { describe, expect, test } from "bun:test"

import {
  notificationChannels,
  notificationPayloads,
  normalizeNotificationPolicy,
  sanitizeNotificationText,
} from "../../../src/cli/cmd/tui/notification-policy"

describe("terminal notification policy", () => {
  test("keeps notifications disabled by default when mode is off", () => {
    expect(notificationPayloads({ category: "run_complete" }, { mode: "off" })).toEqual([])
  })

  test("maps combined mode to desktop and sound payloads", () => {
    const payloads = notificationPayloads(
      {
        category: "approval_waiting",
        message: "Approve shell command with OPENAI_API_KEY=sk-live",
        sessionID: "ses_123",
      },
      { mode: "combined", includeDetails: true },
    )

    expect(payloads.map((payload) => payload.channel)).toEqual(["os", "sound"])
    expect(payloads[0]).toMatchObject({
      category: "approval_waiting",
      title: "Penguin needs approval",
      body: "Approve shell command with OPENAI_API_KEY=[redacted]",
      sessionID: "ses_123",
    })
  })

  test("selects optional novelty sound packs without delivering audio", () => {
    const payloads = notificationPayloads({ category: "run_complete" }, { mode: "sound", soundPack: "penguin" })

    expect(payloads).toEqual([
      {
        channel: "sound",
        category: "run_complete",
        title: "Penguin run complete",
        body: "A run finished.",
        sound: "noot-noot",
        sessionID: undefined,
      },
    ])
  })

  test("filters disabled categories and quiet hours", () => {
    expect(
      notificationPayloads(
        { category: "tool_complete" },
        { mode: "visual", enabledCategories: { tool_complete: false } },
      ),
    ).toEqual([])

    expect(
      notificationPayloads(
        { category: "run_failed" },
        { mode: "visual", quietHours: { start: "22:00", end: "07:00" } },
        new Date("2026-06-27T23:30:00"),
      ),
    ).toEqual([])
  })

  test("sanitizes optional detail text before building payloads", () => {
    expect(sanitizeNotificationText("failed api_key=abc123 token=secret")).toBe(
      "failed api_key=[redacted] token=[redacted]",
    )
    expect(sanitizeNotificationText('failed {"token":"abc123"} Authorization: Bearer sk-live')).toBe(
      'failed {"token":"[redacted]"} Authorization: Bearer [redacted]',
    )
    expect(sanitizeNotificationText('OPENAI_API_KEY=sk-client {"client_secret":"abc"} access_token=tok')).toBe(
      'OPENAI_API_KEY=[redacted] {"client_secret":"[redacted]"} access_token=[redacted]',
    )

    const payloads = notificationPayloads(
      {
        category: "run_failed",
        title: "Failure token=secret",
        message: "The run failed with password=hunter2",
      },
      { mode: "visual", includeDetails: true },
    )

    expect(payloads[0]?.title).toBe("Failure token=[redacted]")
    expect(payloads[0]?.body).toBe("The run failed with password=[redacted]")
  })

  test("documents available delivery channels", () => {
    expect(notificationChannels("visual")).toEqual(["visual"])
    expect(notificationChannels("bell")).toEqual(["bell"])
    expect(notificationChannels("osc")).toEqual(["osc"])
    expect(notificationChannels("os")).toEqual(["os"])
    expect(notificationChannels("terminal")).toEqual(["terminal"])
  })

  test("normalizes backend policy payloads defensively", () => {
    expect(normalizeNotificationPolicy(undefined)).toEqual({ mode: "off", includeDetails: true })
    expect(normalizeNotificationPolicy({ mode: "bogus", soundPack: "penguin" })).toEqual({
      mode: "off",
      soundPack: "penguin",
      includeDetails: true,
      quietHours: undefined,
    })
    expect(normalizeNotificationPolicy({ mode: "combined", includeDetails: false })).toEqual({
      mode: "combined",
      soundPack: "generic",
      includeDetails: false,
      quietHours: undefined,
    })
    expect(
      normalizeNotificationPolicy({
        mode: "combined",
        soundPack: "train_station",
        enabledCategories: {
          question_waiting: false,
          bogus: false,
        },
        includeDetails: true,
        quietHours: { start: "22:00", end: "07:00" },
      }),
    ).toEqual({
      mode: "combined",
      soundPack: "train_station",
      enabledCategories: {
        question_waiting: false,
      },
      includeDetails: true,
      quietHours: { start: "22:00", end: "07:00" },
    })
  })
})
