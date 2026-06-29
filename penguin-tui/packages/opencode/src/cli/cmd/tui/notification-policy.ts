export type AttentionCategory =
  | "run_complete"
  | "run_failed"
  | "approval_waiting"
  | "question_waiting"
  | "provider_auth"
  | "background_subagent"
  | "tool_complete"
  | "reconnect_failed"

export type NotificationMode = "off" | "visual" | "bell" | "osc" | "os" | "terminal" | "sound" | "combined"

export type SoundPack = "generic" | "train_station" | "penguin"

export type NotificationChannel = "visual" | "bell" | "osc" | "os" | "terminal" | "sound"

export type QuietHours = {
  start: string
  end: string
}

export type NotificationPolicy = {
  mode: NotificationMode
  soundPack?: SoundPack
  quietHours?: QuietHours
  enabledCategories?: Partial<Record<AttentionCategory, boolean>>
  includeDetails?: boolean
}

export type AttentionEvent = {
  category: AttentionCategory
  title?: string
  message?: string
  sessionID?: string
}

export type NotificationPayload = {
  channel: NotificationChannel
  category: AttentionCategory
  title: string
  body: string
  sound?: string
  sessionID?: string
}

const DEFAULT_TITLES: Record<AttentionCategory, string> = {
  run_complete: "Penguin run complete",
  run_failed: "Penguin run failed",
  approval_waiting: "Penguin needs approval",
  question_waiting: "Penguin has a question",
  provider_auth: "Penguin provider auth needed",
  background_subagent: "Penguin background agent update",
  tool_complete: "Penguin tool finished",
  reconnect_failed: "Penguin reconnect failed",
}

const DEFAULT_BODIES: Record<AttentionCategory, string> = {
  run_complete: "A run finished.",
  run_failed: "A run failed. Check the terminal for details.",
  approval_waiting: "An approval prompt is waiting in the terminal.",
  question_waiting: "A question is waiting in the terminal.",
  provider_auth: "A provider or MCP server needs authentication.",
  background_subagent: "A background agent reported an update.",
  tool_complete: "A long-running tool finished.",
  reconnect_failed: "The event stream could not reconnect.",
}

const SOUND_NAMES: Record<SoundPack, Record<AttentionCategory, string>> = {
  generic: {
    run_complete: "complete",
    run_failed: "error",
    approval_waiting: "attention",
    question_waiting: "attention",
    provider_auth: "attention",
    background_subagent: "update",
    tool_complete: "complete",
    reconnect_failed: "error",
  },
  train_station: {
    run_complete: "arrival",
    run_failed: "service-disruption",
    approval_waiting: "boarding-call",
    question_waiting: "boarding-call",
    provider_auth: "ticket-check",
    background_subagent: "platform-update",
    tool_complete: "arrival",
    reconnect_failed: "delay-announcement",
  },
  penguin: {
    run_complete: "noot-noot",
    run_failed: "noot-noot-warning",
    approval_waiting: "noot-noot-attention",
    question_waiting: "noot-noot-attention",
    provider_auth: "noot-noot-attention",
    background_subagent: "noot-noot-update",
    tool_complete: "noot-noot",
    reconnect_failed: "noot-noot-warning",
  },
}

export function notificationChannels(mode: NotificationMode): NotificationChannel[] {
  if (mode === "off") return []
  if (mode === "combined") return ["visual", "bell"]
  return [mode]
}

export function notificationPayloads(
  event: AttentionEvent,
  policy: NotificationPolicy,
  now: Date = new Date(),
): NotificationPayload[] {
  if (policy.mode === "off") return []
  if (policy.enabledCategories?.[event.category] === false) return []
  if (policy.quietHours && isQuietTime(now, policy.quietHours)) return []

  const body =
    policy.includeDetails && event.message ? sanitizeNotificationText(event.message) : DEFAULT_BODIES[event.category]
  const title =
    policy.includeDetails && event.title ? sanitizeNotificationText(event.title) : DEFAULT_TITLES[event.category]

  return notificationChannels(policy.mode).map((channel) => ({
    channel,
    category: event.category,
    title,
    body,
    sessionID: event.sessionID,
    sound: channel === "sound" ? SOUND_NAMES[policy.soundPack ?? "generic"][event.category] : undefined,
  }))
}

export function sanitizeNotificationText(input: string): string {
  return input
    .replace(/\b(authorization\s*:\s*)bearer\s+[\w.+/~=-]+/gi, "$1Bearer [redacted]")
    .replace(/\bbearer\s+[\w.+/~=-]+/gi, "Bearer [redacted]")
    .replace(/(["']?(?:api[_-]?key|token|password|secret)["']?\s*:\s*["']?)[^"',}\s]+(["']?)/gi, "$1[redacted]$2")
    .replace(/\b(api[_-]?key|token|password|secret)\s*=\s*["']?[^"',\s]+["']?/gi, "$1=[redacted]")
    .trim()
}

function isQuietTime(now: Date, quietHours: QuietHours): boolean {
  const current = now.getHours() * 60 + now.getMinutes()
  const start = parseClock(quietHours.start)
  const end = parseClock(quietHours.end)
  if (start === end) return false
  if (start < end) return current >= start && current < end
  return current >= start || current < end
}

function parseClock(value: string): number {
  const match = value.match(/^(\d{1,2}):(\d{2})$/)
  if (!match) return 0
  const hours = Math.min(23, Number(match[1]))
  const minutes = Math.min(59, Number(match[2]))
  return hours * 60 + minutes
}
