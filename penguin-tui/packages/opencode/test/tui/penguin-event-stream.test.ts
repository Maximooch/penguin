import { describe, expect, test } from "bun:test"
import {
  cleanPenguinEvent,
  cleanPenguinText,
  parsePenguinSSEEvent,
  type PenguinStreamEvent,
  streamPenguinEvents,
} from "../../src/cli/cmd/tui/context/penguin-event-stream"

function streamResponse(input: string, status = 200): Response {
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(input))
        controller.close()
      },
    }),
    { status },
  )
}

describe("Penguin event stream", () => {
  test("removes finish_response markers from text", () => {
    expect(cleanPenguinText("hello<finish_response>ignored</finish_response> world")).toBe("helloignored world")
    expect(cleanPenguinText("hello</finish_response>")).toBe("hello")
  })

  test("cleans message part update text and delta", () => {
    const event = {
      type: "message.part.updated",
      properties: {
        part: {
          id: "part_1",
          messageID: "msg_1",
          sessionID: "ses_1",
          type: "text",
          text: "hello<finish_response>done</finish_response>",
        },
        delta: "<finish_response>chunk</finish_response>",
      },
    } as PenguinStreamEvent

    const cleaned = cleanPenguinEvent(event) as any

    expect(cleaned.properties.part.text).toBe("hellodone")
    expect(cleaned.properties.delta).toBe("chunk")
  })

  test("parses data lines from an SSE frame", () => {
    const payload = {
      id: "session.status:ses_1:1",
      order: 1,
      time: 100,
      type: "session.status",
      properties: {
        sessionID: "ses_1",
        status: { type: "idle" },
      },
    }

    expect(parsePenguinSSEEvent(`id: ${payload.id}\nevent: message\ndata: ${JSON.stringify(payload)}\n\n`)).toEqual(
      payload,
    )
    expect(parsePenguinSSEEvent("event: ping\n\n")).toBeUndefined()
    expect(parsePenguinSSEEvent("data: not-json\n\n")).toBeUndefined()
  })

  test("streams parsed events with scoped query parameters", async () => {
    const payload = {
      type: "session.status",
      properties: {
        sessionID: "ses_1",
        status: { type: "idle" },
      },
    } as PenguinStreamEvent
    const events: PenguinStreamEvent[] = []
    let requestUrl: URL | undefined
    let requestHeaders: HeadersInit | undefined
    const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
      requestUrl = input instanceof URL ? input : new URL(String(input))
      requestHeaders = init?.headers
      return streamResponse(`data: ${JSON.stringify(payload)}\n\n`)
    }) as typeof fetch

    await streamPenguinEvents({
      baseUrl: "http://127.0.0.1:9000",
      directory: "/tmp/project",
      fetch: fetcher,
      onEvent: (event) => events.push(event),
      sessionID: "ses_1",
      signal: new AbortController().signal,
    })

    expect(requestUrl?.pathname).toBe("/api/v1/events/sse")
    expect(requestUrl?.searchParams.get("session_id")).toBe("ses_1")
    expect(requestUrl?.searchParams.get("directory")).toBe("/tmp/project")
    expect(new Headers(requestHeaders).get("Accept")).toBe("text/event-stream")
    expect(events).toEqual([payload])
  })

  test("reports unauthorized streams without emitting events", async () => {
    const events: PenguinStreamEvent[] = []
    let unauthorized = false
    const fetcher = (async () => streamResponse("", 401)) as unknown as typeof fetch

    await streamPenguinEvents({
      baseUrl: "http://127.0.0.1:9000",
      fetch: fetcher,
      onEvent: (event) => events.push(event),
      onUnauthorized: () => {
        unauthorized = true
      },
      signal: new AbortController().signal,
    })

    expect(unauthorized).toBe(true)
    expect(events).toEqual([])
  })
})
