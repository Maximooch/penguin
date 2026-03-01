import type { Message, Part, Session, Todo } from "@opencode-ai/sdk/v2"
import type { Snapshot } from "@/snapshot"

type MessageWithParts = {
  info: Message
  parts: Part[]
}

type SessionResponse = {
  data?: Session
}

type MessagesResponse = {
  data?: MessageWithParts[]
}

type TodoResponse = {
  data?: Todo[]
}

type DiffResponse = {
  data?: Snapshot.FileDiff[]
}

export type SessionHydrationClient = {
  session: {
    get: (input: { sessionID: string }, options?: { throwOnError?: boolean }) => Promise<SessionResponse>
    messages: (
      input: { sessionID: string; limit?: number },
      options?: { throwOnError?: boolean },
    ) => Promise<MessagesResponse>
    todo?: (input: { sessionID: string }) => Promise<TodoResponse>
    diff?: (input: { sessionID: string }) => Promise<DiffResponse>
  }
}

type SessionHydrationOptions = {
  fallbackSession?: Session
}

function messageCreatedAt(message: Message): number {
  const value = message.time?.created
  return typeof value === "number" ? value : 0
}

function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim().toLowerCase()
}

function textFromParts(parts: Part[] | undefined): string {
  if (!Array.isArray(parts)) return ""
  return normalizeText(
    parts
      .filter((part): part is Part & { type: "text"; text: string } => {
        return part.type === "text" && typeof (part as { text?: unknown }).text === "string"
      })
      .map((part) => part.text)
      .join("\n"),
  )
}

export function mergeHydratedMessages(
  existing: Message[] | undefined,
  hydrated: MessageWithParts[],
  existingParts: Record<string, Part[] | undefined>,
): Message[] {
  const incoming = hydrated.map((row) => row.info)
  if (!Array.isArray(existing) || existing.length === 0) return incoming

  const incomingIDs = new Set(incoming.map((item) => item.id))
  const incomingUsersByText = new Map<string, number[]>()
  for (const row of hydrated) {
    if (row.info.role !== "user") continue
    const text = textFromParts(row.parts)
    if (!text) continue
    const timestamps = incomingUsersByText.get(text) ?? []
    timestamps.push(messageCreatedAt(row.info))
    incomingUsersByText.set(text, timestamps)
  }

  const preserved = existing.filter((item) => {
    if (item.role !== "user") return false
    if (incomingIDs.has(item.id)) return false
    const text = textFromParts(existingParts[item.id])
    if (!text) return true
    const incomingTimes = incomingUsersByText.get(text)
    if (!incomingTimes || incomingTimes.length === 0) return true
    const createdAt = messageCreatedAt(item)
    return !incomingTimes.some((incomingTime) => {
      if (!incomingTime || !createdAt) return true
      return Math.abs(incomingTime - createdAt) <= 30_000
    })
  })

  if (preserved.length === 0) return incoming

  const merged = [...incoming, ...preserved]
  merged.sort((left, right) => {
    const timeDiff = messageCreatedAt(left) - messageCreatedAt(right)
    if (timeDiff !== 0) return timeDiff
    return left.id.localeCompare(right.id)
  })
  return merged
}

function withFallback<T>(request: Promise<{ data?: T }>, fallback: T): Promise<T> {
  return request.then((x) => x.data ?? fallback).catch(() => fallback)
}

export async function hydrateSessionSnapshot(
  client: SessionHydrationClient,
  sessionID: string,
  options?: SessionHydrationOptions,
): Promise<{
  session: Session
  messages: MessageWithParts[]
  todo: Todo[]
  diff: Snapshot.FileDiff[]
}> {
  const fallback = options?.fallbackSession
  const [session, messages, todo, diff] = await Promise.all([
    client.session
      .get({ sessionID }, { throwOnError: true })
      .then((x) => x.data ?? fallback)
      .catch(() => fallback)
      .then((x) => {
        if (x) return x
        throw new Error(`Session ${sessionID} not found`)
      }),
    withFallback(client.session.messages({ sessionID, limit: 300 }), []),
    client.session.todo ? withFallback(client.session.todo({ sessionID }), []) : Promise.resolve([]),
    client.session.diff ? withFallback(client.session.diff({ sessionID }), []) : Promise.resolve([]),
  ])

  return {
    session,
    messages,
    todo,
    diff,
  }
}
