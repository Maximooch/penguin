export const DEFAULT_PENGUIN_STALE_MS = 15_000

export type PenguinRunStateType = "idle" | "pending" | "running" | "reconnecting" | "stale"

export type PenguinStreamInfo = {
  lastEventAt?: number
  status?: "idle" | "connecting" | "connected" | "reconnecting" | "denied"
}

type SessionStatus = {
  type?: string
}

type TimedMessage = {
  finish?: string
  role?: string
  time?: {
    completed?: number
    created?: number
  }
}

type TimedPart = {
  state?: {
    status?: string
  }
  time?: {
    created?: number
    end?: number
    start?: number
  }
  type?: string
}

export type PenguinRunState = {
  elapsedMs: number
  lastEventAgeMs?: number
  startedAt?: number
  type: PenguinRunStateType
}

export function isPenguinStatusBusy(status?: SessionStatus): boolean {
  return !!status?.type && status.type !== "idle"
}

export function isPenguinPartActive(part: TimedPart): boolean {
  const state = part.state?.status
  if (state === "pending" || state === "running") return true
  if (part.type === "reasoning" && part.time?.start !== undefined && part.time.end === undefined) return true
  return false
}

export function isPenguinAssistantOpen(input: { message?: TimedMessage; parts?: TimedPart[] }): boolean {
  const message = input.message
  if (!message || message.role !== "assistant") return false
  if (message.time?.completed !== undefined) return false

  const finish = message.finish
  if (finish && !["tool-calls", "unknown"].includes(finish)) return false

  if (input.parts?.some(isPenguinPartActive)) return true
  return true
}

export function derivePenguinRunState(input: {
  assistant?: TimedMessage
  assistantParts?: TimedPart[]
  localStartedAt?: number
  now: number
  pending?: boolean
  sessionStatus?: SessionStatus
  staleAfterMs?: number
  stream?: PenguinStreamInfo
  user?: TimedMessage
}): PenguinRunState {
  const statusBusy = isPenguinStatusBusy(input.sessionStatus)
  const assistantOpen = isPenguinAssistantOpen({
    message: input.assistant,
    parts: input.assistantParts,
  })
  const active = !!input.pending || statusBusy || assistantOpen

  if (!active) {
    return {
      elapsedMs: 0,
      type: "idle",
    }
  }

  const startedAt = input.localStartedAt ?? input.user?.time?.created ?? input.assistant?.time?.created ?? input.now
  const elapsedMs = Math.max(0, input.now - startedAt)
  const lastEventAgeMs =
    input.stream?.lastEventAt === undefined ? undefined : Math.max(0, input.now - input.stream.lastEventAt)

  if (input.stream?.status === "reconnecting" || input.stream?.status === "connecting") {
    return {
      elapsedMs,
      lastEventAgeMs,
      startedAt,
      type: "reconnecting",
    }
  }

  const staleAfterMs = input.staleAfterMs ?? DEFAULT_PENGUIN_STALE_MS
  const staleWithoutEvents = input.stream?.lastEventAt === undefined && elapsedMs >= staleAfterMs
  const staleSinceLastEvent = lastEventAgeMs !== undefined && lastEventAgeMs >= staleAfterMs
  if (staleWithoutEvents || staleSinceLastEvent || input.stream?.status === "denied") {
    return {
      elapsedMs,
      lastEventAgeMs,
      startedAt,
      type: "stale",
    }
  }

  return {
    elapsedMs,
    lastEventAgeMs,
    startedAt,
    type: input.pending && !statusBusy && !assistantOpen ? "pending" : "running",
  }
}
