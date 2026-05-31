export type PenguinStreamEvent = {
  type: string
  properties: Record<string, unknown>
}

export type PenguinEventStreamOptions<T extends PenguinStreamEvent = PenguinStreamEvent> = {
  baseUrl: string | URL
  directory?: string
  fetch: typeof fetch
  isCurrentSession?: (sessionID?: string) => boolean
  onEvent: (event: T) => void
  onOpen?: () => void
  onUnauthorized?: () => void
  sessionID?: string
  signal: AbortSignal
}

export function cleanPenguinEvent<T extends PenguinStreamEvent>(event: T): T {
  if (event.type !== "message.part.updated") return event

  const part = event.properties.part
  if (part && typeof part === "object") {
    const textPart = part as { text?: unknown; type?: unknown }
    if (textPart.type === "text" && typeof textPart.text === "string") {
      const text = cleanPenguinText(textPart.text)
      if (text !== textPart.text) textPart.text = text
    }
  }

  const delta = event.properties.delta
  if (typeof delta === "string") {
    const cleanDelta = cleanPenguinText(delta)
    if (cleanDelta !== delta) event.properties.delta = cleanDelta
  }

  return event
}

export function cleanPenguinText(value: string): string {
  return value.replace(/<\/?finish_response\b[^>]*>?/g, "")
}

export function parsePenguinSSEEvent<T extends PenguinStreamEvent = PenguinStreamEvent>(input: string): T | undefined {
  const data = input
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim())
    .join("\n")
  if (!data) return undefined

  try {
    return JSON.parse(data) as T
  } catch {
    return undefined
  }
}

export async function streamPenguinEvents<T extends PenguinStreamEvent = PenguinStreamEvent>(
  options: PenguinEventStreamOptions<T>,
): Promise<void> {
  const base = new URL("/api/v1/events/sse", options.baseUrl)
  if (options.sessionID) base.searchParams.set("session_id", options.sessionID)
  if (options.directory) base.searchParams.set("directory", options.directory)

  const res = await options.fetch(base, {
    signal: options.signal,
    headers: {
      Accept: "text/event-stream",
    },
  })

  if (!res.ok) {
    if (res.status === 401) options.onUnauthorized?.()
    return
  }

  options.onOpen?.()

  const reader = res.body?.getReader()
  if (!reader) return

  const decoder = new TextDecoder()
  const state = { buffer: "" }

  while (true) {
    if (options.signal.aborted) break

    const chunk = await reader.read()
    if (chunk.done) break

    if (options.isCurrentSession && !options.isCurrentSession(options.sessionID)) {
      try {
        await reader.cancel()
      } catch {}
      break
    }

    state.buffer += decoder.decode(chunk.value, { stream: true })
    const parts = state.buffer.split("\n\n")
    state.buffer = parts.pop() ?? ""
    for (const part of parts) {
      const event = parsePenguinSSEEvent<T>(part)
      if (!event) continue
      options.onEvent(cleanPenguinEvent(event))
    }
  }
}
