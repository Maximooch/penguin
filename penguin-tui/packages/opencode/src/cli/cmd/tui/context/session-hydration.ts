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
