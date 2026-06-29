import {
  normalizeNotificationPolicy,
  type NotificationMode,
  type NotificationPolicy,
  type QuietHours,
  type SoundPack,
} from "./notification-policy"

export const NOTIFICATION_POLICY_OVERRIDE_KEY = "notification_policy_override"

export function withNotificationMode(policy: NotificationPolicy, mode: NotificationMode): NotificationPolicy {
  return normalizeNotificationPolicy({ ...policy, mode })
}

export function withNotificationSoundPack(policy: NotificationPolicy, soundPack: SoundPack): NotificationPolicy {
  return normalizeNotificationPolicy({ ...policy, soundPack })
}

export function withNotificationDetails(policy: NotificationPolicy, includeDetails: boolean): NotificationPolicy {
  return normalizeNotificationPolicy({ ...policy, includeDetails })
}

export function withNotificationQuietHours(
  policy: NotificationPolicy,
  quietHours: QuietHours | undefined,
): NotificationPolicy {
  return normalizeNotificationPolicy({ ...policy, quietHours })
}

export function parseQuietHoursInput(input: string): QuietHours | undefined {
  const match = input.trim().match(/^(\d{1,2}:\d{2})\s*(?:-|–|to)\s*(\d{1,2}:\d{2})$/i)
  if (!match) return
  const start = normalizeClock(match[1])
  const end = normalizeClock(match[2])
  if (!start || !end || start === end) return
  return { start, end }
}

export function notificationPolicySummary(policy: NotificationPolicy): string {
  const parts = [`mode ${policy.mode}`]
  if (policy.mode === "sound") parts.push(`sound ${policy.soundPack ?? "generic"}`)
  if (policy.includeDetails) parts.push("details on")
  if (policy.quietHours) parts.push(`quiet ${policy.quietHours.start}-${policy.quietHours.end}`)
  return parts.join(" · ")
}

function normalizeClock(input: string): string | undefined {
  const match = input.match(/^(\d{1,2}):(\d{2})$/)
  if (!match) return
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (!Number.isInteger(hours) || !Number.isInteger(minutes)) return
  if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return
  return `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}`
}
