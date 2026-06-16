import { describe, expect, test } from "bun:test"
import {
  createPenguinSession,
  emitPenguinOptimisticPrompt,
  formatPenguinPromptFailure,
  isPenguinSyntheticModel,
  recoverPenguinPromptFailure,
  resolveSessionID,
  sendPenguinPrompt,
  shouldStripPenguinVirtualPart,
} from "../../src/cli/cmd/tui/component/prompt/penguin-send"

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "Content-Type": "application/json",
    },
  })
}

describe("Penguin prompt send helper", () => {
  test("resolves session ids from OpenCode and Penguin response shapes", () => {
    expect(resolveSessionID(" ses_1 ")).toBe("ses_1")
    expect(resolveSessionID({ id: "ses_2" })).toBe("ses_2")
    expect(resolveSessionID({ data: { id: "ses_3" } })).toBe("ses_3")
    expect(resolveSessionID({ data: {} })).toBeUndefined()
  })

  test("creates a Penguin session through the compatibility route", async () => {
    let requestUrl: URL | undefined
    let body: Record<string, unknown> | undefined
    const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
      requestUrl = input instanceof URL ? input : new URL(String(input))
      body = JSON.parse(String(init?.body))
      return jsonResponse({ data: { id: "ses_created" } })
    }) as unknown as typeof fetch

    const sessionID = await createPenguinSession({
      agentMode: "build",
      baseUrl: "http://127.0.0.1:9000",
      directory: "/tmp/project",
      fetch: fetcher,
      model: {
        providerID: "anthropic",
        modelID: "claude-sonnet-4",
      },
      variant: "thinking",
    })

    expect(sessionID).toBe("ses_created")
    expect(requestUrl?.pathname).toBe("/session")
    expect(requestUrl?.searchParams.get("directory")).toBe("/tmp/project")
    expect(body).toEqual({
      agent_mode: "build",
      providerID: "anthropic",
      modelID: "claude-sonnet-4",
      variant: "thinking",
    })
  })

  test("rejects synthetic fallback models before creating Penguin sessions", async () => {
    let called = false
    const fetcher = (async () => {
      called = true
      return jsonResponse({ data: { id: "ses_created" } })
    }) as unknown as typeof fetch

    expect(isPenguinSyntheticModel({ providerID: "penguin", modelID: "penguin-default" })).toBe(true)
    await expect(
      createPenguinSession({
        agentMode: "build",
        baseUrl: "http://127.0.0.1:9000",
        directory: "/tmp/project",
        fetch: fetcher,
        model: {
          providerID: "penguin",
          modelID: "penguin-default",
        },
      }),
    ).rejects.toThrow("Provider configuration is still loading")

    expect(called).toBe(false)
  })

  test("rejects empty session create responses with diagnostic details", async () => {
    const fetcher = (async () => jsonResponse({ data: {} })) as unknown as typeof fetch

    await expect(
      createPenguinSession({
        agentMode: "plan",
        baseUrl: "http://127.0.0.1:9000",
        directory: "/tmp/project",
        fetch: fetcher,
        model: {
          providerID: "openai",
          modelID: "gpt-5",
        },
      }),
    ).rejects.toThrow("Session create returned empty id")
  })

  test("strips image virtual text for Penguin file parts only", () => {
    expect(shouldStripPenguinVirtualPart({ type: "file", mime: "image/png" })).toBe(true)
    expect(shouldStripPenguinVirtualPart({ type: "file", mime: "application/pdf" })).toBe(false)
    expect(shouldStripPenguinVirtualPart({ type: "text" })).toBe(false)
  })

  test("emits a single optimistic user message, part, and busy status", () => {
    const events: Array<{ type: string; event: unknown }> = []

    const result = emitPenguinOptimisticPrompt({
      agentName: "general",
      emit: (type, event) => events.push({ type, event }),
      messageID: "msg_1",
      model: {
        providerID: "anthropic",
        modelID: "claude-sonnet-4",
      },
      now: 123,
      partID: "part_1",
      sessionID: "ses_1",
      text: "hello",
    })

    expect(result.user).toMatchObject({
      id: "msg_1",
      sessionID: "ses_1",
      role: "user",
      agent: "general",
      model: {
        providerID: "anthropic",
        modelID: "claude-sonnet-4",
      },
      time: {
        created: 123,
      },
    })
    expect(result.part).toMatchObject({
      id: "part_1",
      messageID: "msg_1",
      sessionID: "ses_1",
      type: "text",
      text: "hello",
      time: {
        start: 123,
        end: 123,
      },
    })
    expect(events.map((event) => event.type)).toEqual(["message.updated", "message.part.updated", "session.status"])
  })

  test("posts Penguin prompts with explicit compatibility payload fields", async () => {
    let requestUrl: URL | undefined
    let body: Record<string, unknown> | undefined
    const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
      requestUrl = input instanceof URL ? input : new URL(String(input))
      body = JSON.parse(String(init?.body))
      return new Response("", { status: 204 })
    }) as unknown as typeof fetch

    const result = await sendPenguinPrompt({
      agentMode: "build",
      agentName: "general",
      baseUrl: "http://127.0.0.1:9000",
      directory: "/tmp/project",
      fetch: fetcher,
      messageID: "msg_1",
      model: {
        providerID: "anthropic",
        modelID: "claude-sonnet-4",
      },
      parts: [{ type: "file", mime: "image/png", url: "data:image/png;base64,abc" }],
      serviceTier: "fast",
      sessionID: "ses_1",
      text: "hello",
      variant: "thinking",
    })

    expect(result).toEqual({ ok: true })
    expect(requestUrl?.pathname).toBe("/api/v1/chat/message")
    expect(body).toEqual({
      text: "hello",
      model: "anthropic/claude-sonnet-4",
      session_id: "ses_1",
      agent_id: "general",
      agent_mode: "build",
      directory: "/tmp/project",
      streaming: true,
      variant: "thinking",
      service_tier: "fast",
      client_message_id: "msg_1",
      parts: [{ type: "file", mime: "image/png", url: "data:image/png;base64,abc" }],
    })
  })

  test("rejects synthetic fallback models before posting Penguin prompts", async () => {
    let called = false
    const fetcher = (async () => {
      called = true
      return new Response("", { status: 204 })
    }) as unknown as typeof fetch

    await expect(
      sendPenguinPrompt({
        agentMode: "build",
        agentName: "general",
        baseUrl: "http://127.0.0.1:9000",
        directory: "/tmp/project",
        fetch: fetcher,
        messageID: "msg_1",
        model: {
          providerID: "penguin",
          modelID: "penguin-default",
        },
        parts: [],
        sessionID: "ses_1",
        text: "hello",
      }),
    ).resolves.toEqual({
      ok: false,
      details: "Provider configuration is still loading. Try again once the model list finishes loading.",
    })
    expect(called).toBe(false)
  })

  test("returns structured prompt send failures", async () => {
    const fetcher = (async () => new Response("unauthorized", { status: 401 })) as unknown as typeof fetch

    await expect(
      sendPenguinPrompt({
        agentMode: "build",
        agentName: "general",
        baseUrl: "http://127.0.0.1:9000",
        directory: "/tmp/project",
        fetch: fetcher,
        messageID: "msg_1",
        model: {
          providerID: "anthropic",
          modelID: "claude-sonnet-4",
        },
        parts: [],
        sessionID: "ses_1",
        text: "hello",
      }),
    ).resolves.toEqual({
      ok: false,
      status: 401,
      details: "unauthorized",
    })

    expect(formatPenguinPromptFailure({ status: 401 })).toContain("local auth")
  })

  test("recovers failed optimistic sends by clearing pending state and emitting idle", () => {
    const events: unknown[] = []
    let cleared = false

    recoverPenguinPromptFailure({
      sessionID: "ses_1",
      clear: () => {
        cleared = true
      },
      emit: (_type, event) => events.push(event),
    })

    expect(cleared).toBe(true)
    expect(events).toEqual([
      {
        type: "session.status",
        properties: {
          sessionID: "ses_1",
          status: { type: "idle" },
        },
      },
    ])
  })
})
