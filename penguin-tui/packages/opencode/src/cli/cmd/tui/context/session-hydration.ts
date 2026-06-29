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
  if (typeof value === "number") return value

  const match = /^msg_(\d{10,13})(?:[._]\d+)?/.exec(message.id)
  if (!match) return Number.MAX_SAFE_INTEGER

  const raw = match[1]
  const stamp = Number(raw)
  if (!Number.isFinite(stamp)) return Number.MAX_SAFE_INTEGER
  return raw.length === 10 ? stamp * 1000 : stamp
}

function parentID(message: Message): string | undefined {
  if (message.role !== "assistant") return undefined
  const value = message.parentID
  if (!value || value === "root") return undefined
  return value
}

export function compareMessagesByCreated(left: Message, right: Message): number {
  const leftParent = parentID(left)
  if (leftParent && leftParent === right.id) return 1

  const rightParent = parentID(right)
  if (rightParent && rightParent === left.id) return -1

  const diff = messageCreatedAt(left) - messageCreatedAt(right)
  if (diff !== 0) return diff
  return left.id.localeCompare(right.id)
}

function latestUserBefore(messages: Message[], beforeIndex: number): Message | undefined {
  for (let index = beforeIndex - 1; index >= 0; index--) {
    const item = messages[index]
    if (item?.role === "user") return item
  }
  return undefined
}

function inferLiveAssistantParent(existing: Message[], incoming: Message, insertionIndex: number): Message {
  if (incoming.role !== "assistant") return incoming
  if (parentID(incoming)) return incoming

  const parent = latestUserBefore(existing, insertionIndex)
  if (!parent) return incoming

  const incomingCreatedAt = messageCreatedAt(incoming)
  const parentCreatedAt = messageCreatedAt(parent)
  if (incomingCreatedAt > parentCreatedAt) return incoming
  if (incoming.time?.completed !== undefined && incoming.time.completed < parentCreatedAt) {
    return incoming
  }

  return {
    ...incoming,
    parentID: parent.id,
  } as Message
}

export function upsertPenguinMessage(existing: Message[] | undefined, incoming: Message): Message[] {
  if (!Array.isArray(existing) || existing.length === 0) return [incoming]
  const match = existing.findIndex((item) => item.id === incoming.id)
  const matched = match === -1 ? undefined : existing[match]
  const matchedParentID = matched ? parentID(matched) : undefined
  const inferredIncoming =
    matchedParentID && !parentID(incoming)
      ? ({
          ...incoming,
          parentID: matchedParentID,
        } as Message)
      : incoming
  const normalized = inferLiveAssistantParent(existing, inferredIncoming, match === -1 ? existing.length : match)
  if (match !== -1) {
    return existing.map((item, index) => (index === match ? normalized : item)).toSorted(compareMessagesByCreated)
  }
  return [...existing, normalized].toSorted(compareMessagesByCreated)
}

function insertPreservedMessages(hydrated: Message[], preserved: Message[]): Message[] {
  const merged = [...hydrated]
  for (const message of preserved.toSorted(compareMessagesByCreated)) {
    const insertAt = merged.findIndex((item) => compareMessagesByCreated(message, item) < 0)
    if (insertAt === -1) {
      merged.push(message)
      continue
    }
    merged.splice(insertAt, 0, message)
  }
  return merged
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

  return insertPreservedMessages(incoming, preserved)
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
