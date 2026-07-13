import { describe, expect, test } from "bun:test"
import {
  abortPenguinSession,
  createPenguinSession,
  emitPenguinOptimisticPrompt,
  fetchPenguinTerminalState,
  formatPenguinPromptFailure,
  formatPenguinPromptTerminalDetails,
  formatPenguinPromptTerminal,
  getPenguinPromptContinuation,
  isPenguinSyntheticModel,
  isPenguinTerminalInterruptible,
  parsePenguinPromptTerminal,
  recoverPenguinPromptFailure,
  resolveSessionID,
  sendPenguinPrompt,
  sendPenguinContinuation,
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
      baseUrl: "http://127.0.0.1:8080",
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
        baseUrl: "http://127.0.0.1:8080",
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
        baseUrl: "http://127.0.0.1:8080",
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
      emit: (event) => {
        events.push({ type: event.type, event })
      },
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
      return jsonResponse({
        response: "done",
        partial_response: "",
        action_results: [],
        action_count: 0,
        status: "completed",
        terminal_reason: "completed",
        state: "completed",
        completed: true,
        recoverable: false,
        aborted: false,
        cancelled: false,
        continuation: null,
        actions: [],
      })
    }) as unknown as typeof fetch

    const result = await sendPenguinPrompt({
      agentMode: "build",
      agentName: "general",
      baseUrl: "http://127.0.0.1:8080",
      directory: "/tmp/project",
      fetch: fetcher,
      clientPartID: "part_1",
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

    expect(result).toEqual({
      ok: true,
      terminal: expect.objectContaining({
        completed: true,
        legacy: false,
        status: "completed",
      }),
    })
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
      client_part_id: "part_1",
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
        baseUrl: "http://127.0.0.1:8080",
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
        baseUrl: "http://127.0.0.1:8080",
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

  test("does not turn unreadable or non-object 2xx bodies into completion", async () => {
    const input = {
      agentMode: "build" as const,
      agentName: "general",
      baseUrl: "http://127.0.0.1:8080",
      directory: "/tmp/project",
      messageID: "msg_1",
      model: { providerID: "openai", modelID: "gpt-5" },
      parts: [],
      sessionID: "ses_1",
      text: "hello",
    }
    const primitive = (async () => jsonResponse("completed")) as unknown as typeof fetch
    const unreadable = (async () =>
      ({
        ok: true,
        status: 200,
        text: async () => {
          throw new Error("body disconnected")
        },
      }) as unknown as Response) as unknown as typeof fetch

    await expect(sendPenguinPrompt({ ...input, fetch: primitive })).resolves.toMatchObject({
      ok: false,
      status: 200,
    })
    await expect(sendPenguinPrompt({ ...input, fetch: unreadable })).resolves.toMatchObject({
      ok: false,
      status: 200,
      details: "Failed to read the Penguin terminal response.",
    })
  })

  test("rejects empty and contradictory 2xx terminal truth", async () => {
    const input = {
      agentMode: "build" as const,
      agentName: "general",
      baseUrl: "http://127.0.0.1:8080",
      directory: "/tmp/project",
      messageID: "msg_1",
      model: { providerID: "openai", modelID: "gpt-5" },
      parts: [],
      sessionID: "ses_1",
      text: "hello",
    }
    const empty = (async () => new Response("", { status: 204 })) as unknown as typeof fetch
    const contradictory = (async () =>
      jsonResponse({
        status: "completed",
        state: "failed",
        completed: true,
        recoverable: false,
      })) as unknown as typeof fetch

    await expect(sendPenguinPrompt({ ...input, fetch: empty })).resolves.toMatchObject({
      ok: false,
      status: 204,
    })
    await expect(sendPenguinPrompt({ ...input, fetch: contradictory })).resolves.toMatchObject({
      ok: false,
      status: 200,
      details: expect.stringContaining("contradicts"),
    })
  })

  test("rejects status and cancellation contradictions in 2xx terminal truth", async () => {
    const input = {
      agentMode: "build" as const,
      agentName: "general",
      baseUrl: "http://127.0.0.1:8080",
      directory: "/tmp/project",
      messageID: "msg_1",
      model: { providerID: "openai", modelID: "gpt-5" },
      parts: [],
      sessionID: "ses_1",
      text: "hello",
    }
    const impossibleCompletion = (async () =>
      jsonResponse({
        status: "max_iterations",
        state: "completed",
        completed: true,
        recoverable: false,
      })) as unknown as typeof fetch
    const impossibleCancellation = (async () =>
      jsonResponse({
        status: "cancelled",
        state: "cancelled",
        completed: false,
        recoverable: true,
        cancelled: false,
      })) as unknown as typeof fetch
    const impossibleDualCancellation = (async () =>
      jsonResponse({
        status: "cancelled",
        state: "cancelled",
        completed: false,
        recoverable: true,
        aborted: true,
        cancelled: true,
      })) as unknown as typeof fetch

    await expect(sendPenguinPrompt({ ...input, fetch: impossibleCompletion })).resolves.toMatchObject({
      ok: false,
      details: expect.stringContaining("contradicts status"),
    })
    await expect(sendPenguinPrompt({ ...input, fetch: impossibleCancellation })).resolves.toMatchObject({
      ok: false,
      details: expect.stringContaining("cancelled status contradicts"),
    })
    await expect(sendPenguinPrompt({ ...input, fetch: impossibleDualCancellation })).resolves.toMatchObject({
      ok: false,
      details: expect.stringContaining("cannot be both aborted and cancelled"),
    })
  })

  test("hydrates and renders persistent incomplete terminal details", async () => {
    let requestUrl: URL | undefined
    const fetcher = (async (input: RequestInfo | URL) => {
      requestUrl = input instanceof URL ? input : new URL(String(input))
      return jsonResponse({
        response: "partial",
        partial_response: "kept partial output",
        action_results: [{ action: "write", status: "completed" }],
        action_count: 1,
        status: "request_gate_timeout",
        terminal_reason: "request_gate_timeout",
        state: "stalled",
        completed: false,
        recoverable: true,
        aborted: false,
        cancelled: false,
        error: { code: "session_busy", message: "another request owns the session" },
        continuation: null,
        actions: [],
      })
    }) as unknown as typeof fetch

    const terminal = await fetchPenguinTerminalState({
      baseUrl: "http://127.0.0.1:8080",
      directory: "/tmp/project",
      fetch: fetcher,
      sessionID: "ses/1",
    })

    expect(requestUrl?.pathname).toBe("/api/v1/session/ses%2F1/terminal")
    expect(requestUrl?.searchParams.get("directory")).toBe("/tmp/project")
    expect(isPenguinTerminalInterruptible(terminal)).toBe(true)
    expect(formatPenguinPromptTerminalDetails(terminal!)).toBe(
      [
        "Penguin stopped: request gate timeout",
        "partial: kept partial output",
        "tool results: 1",
        "detail: session busy: another request owns the session",
        "Esc interrupt",
      ].join("\n"),
    )
  })

  test("preserves a recoverable non-completed terminal response", async () => {
    const fetcher = (async () =>
      jsonResponse({
        response: "Partial answer",
        partial_response: "Partial answer",
        action_results: [{ action: "read", status: "completed" }],
        action_count: 1,
        status: "provider_recoverable_error",
        state: "provider_exhausted",
        terminal_reason: "provider_retry_exhausted",
        completed: false,
        recoverable: true,
        aborted: false,
        cancelled: false,
        iterations: 3,
        continuation: {
          available: true,
          action: "retry",
          endpoint: "/api/v1/chat/continue",
          label: "Retry",
          method: "POST",
          request: {
            continuation: {
              generation: 7,
            },
          },
        },
        actions: [
          { action: "retry", label: "Retry" },
          { action: "resume", label: "Resume" },
        ],
      })) as unknown as typeof fetch

    const result = await sendPenguinPrompt({
      agentMode: "build",
      agentName: "general",
      baseUrl: "http://127.0.0.1:8080",
      directory: "/tmp/project",
      fetch: fetcher,
      messageID: "msg_1",
      model: {
        providerID: "openai",
        modelID: "gpt-5",
      },
      parts: [],
      sessionID: "ses_1",
      text: "hello",
    })

    expect(result).toEqual({
      ok: true,
      terminal: expect.objectContaining({
        actionCount: 1,
        actions: [
          { action: "retry", label: "Retry" },
          { action: "resume", label: "Resume" },
        ],
        completed: false,
        continuation: {
          available: true,
          action: "retry",
          endpoint: "/api/v1/chat/continue",
          label: "Retry",
          method: "POST",
          request: {
            continuation: {
              generation: 7,
            },
          },
        },
        iterations: 3,
        partialResponse: "Partial answer",
        recoverable: true,
        status: "provider_recoverable_error",
        terminalReason: "provider_retry_exhausted",
      }),
    })
    if (!result.ok) throw new Error("expected terminal response")
    expect(getPenguinPromptContinuation(result.terminal)).toEqual({
      action: "retry",
      endpoint: "/api/v1/chat/continue",
      label: "Retry",
      method: "POST",
      request: {
        continuation: {
          generation: 7,
        },
      },
    })
    expect(formatPenguinPromptTerminal(result.terminal)).toBe(
      "Penguin stopped: provider retry exhausted · available: Retry, Resume",
    )
  })

  test("infers completed legacy and explicit terminal response shapes", () => {
    expect(parsePenguinPromptTerminal({ response: "done" })).toMatchObject({
      completed: true,
      legacy: true,
      response: "done",
      status: "completed",
    })
    expect(
      parsePenguinPromptTerminal({
        completed: false,
        status: "max_iterations",
        terminal_reason: "iteration_limit",
      }),
    ).toMatchObject({
      completed: false,
      legacy: false,
      status: "max_iterations",
      terminalReason: "iteration_limit",
    })
  })

  test("keeps transport cancellation distinct from user abort", () => {
    const terminal = parsePenguinPromptTerminal({
      status: "cancelled",
      cancelled: true,
      aborted: false,
      completed: false,
    })

    expect(terminal.cancelled).toBe(true)
    expect(terminal.aborted).toBe(false)
  })

  test("aborts a stuck prompt POST at the injected deadline", async () => {
    const observed = { aborted: false }
    const fetcher = ((_: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => {
            observed.aborted = true
            reject(init.signal?.reason ?? new DOMException("Aborted", "AbortError"))
          },
          { once: true },
        )
      })) as typeof fetch

    const result = await sendPenguinPrompt({
      agentMode: "build",
      agentName: "general",
      baseUrl: "http://127.0.0.1:8080",
      directory: "/tmp/project",
      fetch: fetcher,
      messageID: "msg_1",
      model: { providerID: "openai", modelID: "gpt-5" },
      parts: [],
      sessionID: "ses_1",
      text: "hello",
      timeoutMs: 5,
    })

    expect(observed.aborted).toBe(true)
    expect(result).toMatchObject({
      ok: false,
      timedOut: true,
    })
    expect(formatPenguinPromptFailure(result as { error?: unknown; timedOut?: boolean })).toContain("timed out")
  })

  test("explicitly aborts backend work after cancelling the local prompt fetch", async () => {
    const state = {
      abortPath: "",
      backendActive: true,
      localAborted: false,
    }
    const fetcher = ((input: RequestInfo | URL, init?: RequestInit) => {
      const url = input instanceof URL ? input : new URL(String(input))
      if (url.pathname.endsWith("/abort")) {
        state.abortPath = `${url.pathname}?${url.searchParams.toString()}`
        state.backendActive = false
        return Promise.resolve(jsonResponse(true))
      }
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => {
            state.localAborted = true
            reject(init.signal?.reason ?? new DOMException("Aborted", "AbortError"))
          },
          { once: true },
        )
      })
    }) as typeof fetch
    const controller = new AbortController()
    const pending = sendPenguinPrompt({
      agentMode: "build",
      agentName: "general",
      baseUrl: "http://127.0.0.1:8080",
      directory: "/tmp/project",
      fetch: fetcher,
      messageID: "msg_1",
      model: { providerID: "openai", modelID: "gpt-5" },
      parts: [],
      sessionID: "ses/1",
      signal: controller.signal,
      text: "hello",
      timeoutMs: 60_000,
    })

    controller.abort(new DOMException("Interrupted", "AbortError"))
    await expect(pending).resolves.toMatchObject({ aborted: true, ok: false })
    expect(state.localAborted).toBe(true)
    expect(state.backendActive).toBe(true)

    await expect(
      abortPenguinSession({
        baseUrl: "http://127.0.0.1:8080",
        directory: "/tmp/project",
        fetch: fetcher,
        sessionID: "ses/1",
      }),
    ).resolves.toBe(true)
    expect(state.backendActive).toBe(false)
    expect(state.abortPath).toBe("/session/ses%2F1/abort?directory=%2Ftmp%2Fproject")
  })

  test("posts only the server-supplied typed continuation request after selection", async () => {
    const state: {
      body?: Record<string, unknown>
      method?: string
      url?: string
    } = {}
    const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
      state.url = String(input)
      state.method = init?.method
      state.body = JSON.parse(String(init?.body))
      return jsonResponse({
        status: "completed",
        state: "completed",
        terminal_reason: "completed",
        completed: true,
        recoverable: false,
      })
    }) as typeof fetch
    const terminal = parsePenguinPromptTerminal({
      status: "provider_recoverable_error",
      state: "provider_exhausted",
      completed: false,
      recoverable: true,
      continuation: {
        available: true,
        action: "retry",
        label: "Retry",
        method: "POST",
        endpoint: "/api/v1/chat/message",
        request: {
          session_id: "ses_1",
          continuation: {
            action: "retry",
            previous_status: "provider_recoverable_error",
            request_id: "req_1",
            generation: 7,
          },
        },
      },
    })

    await expect(
      sendPenguinContinuation({
        baseUrl: "http://127.0.0.1:8080",
        fetch: fetcher,
        terminal,
      }),
    ).resolves.toMatchObject({
      ok: true,
      terminal: {
        completed: true,
        state: "completed",
      },
    })
    expect(state.url).toBe("http://127.0.0.1:8080/api/v1/chat/message")
    expect(state.method).toBe("POST")
    expect(state.body).toEqual({
      session_id: "ses_1",
      continuation: {
        action: "retry",
        previous_status: "provider_recoverable_error",
        request_id: "req_1",
        generation: 7,
      },
    })
  })

  test("recovers failed optimistic sends without synthesizing terminal status", () => {
    const events: unknown[] = []
    let cleared = false

    recoverPenguinPromptFailure({
      messageID: "msg_1",
      sessionID: "ses_1",
      clear: () => {
        cleared = true
      },
      emit: (_type, event) => events.push(event),
    })

    expect(cleared).toBe(true)
    expect(events).toEqual([])
  })
})
