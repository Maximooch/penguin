import { describe, expect, test } from "bun:test"

import {
  notificationPolicySummary,
  parseQuietHoursInput,
  withNotificationDetails,
  withNotificationMode,
  withNotificationQuietHours,
  withNotificationSoundPack,
} from "../../../src/cli/cmd/tui/notification-settings"

describe("terminal notification settings helpers", () => {
  test("builds policy updates defensively", () => {
    const base = { mode: "off" as const }

    expect(withNotificationMode(base, "bell")).toEqual({
      mode: "bell",
      soundPack: "generic",
      includeDetails: true,
      quietHours: undefined,
    })
    expect(withNotificationSoundPack(base, "penguin")).toEqual({
      mode: "off",
      soundPack: "penguin",
      includeDetails: true,
      quietHours: undefined,
    })
    expect(withNotificationDetails(base, true).includeDetails).toBe(true)
  })

  test("parses quiet hours in 24-hour local time", () => {
    expect(parseQuietHoursInput("22:00-07:30")).toEqual({ start: "22:00", end: "07:30" })
    expect(parseQuietHoursInput("8:05 to 17:45")).toEqual({ start: "08:05", end: "17:45" })
    expect(parseQuietHoursInput("25:00-07:00")).toBeUndefined()
    expect(parseQuietHoursInput("08:00-08:00")).toBeUndefined()
  })

  test("summarizes the active local policy", () => {
    const policy = withNotificationQuietHours(
      withNotificationDetails({ mode: "sound", soundPack: "train_station" }, true),
      { start: "22:00", end: "07:00" },
    )

    expect(notificationPolicySummary(policy)).toBe("mode sound · sound train_station · details on · quiet 22:00-07:00")
  })
})
