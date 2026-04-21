import { describe, expect, test } from "bun:test"
import {
  createOptimisticPenguinEvents,
  createPenguinSession,
  parsePenguinPromptCommand,
  resolvePenguinSessionID,
} from "../../../src/cli/cmd/tui/component/prompt/penguin-runtime"

describe("prompt penguin runtime", () => {
  test("resolves session ids from direct and wrapped responses", () => {
    expect(resolvePenguinSessionID("ses_direct")).toBe("ses_direct")
    expect(resolvePenguinSessionID({ id: "ses_object" })).toBe("ses_object")
    expect(resolvePenguinSessionID({ data: { id: "ses_nested" } })).toBe("ses_nested")
  })

  test("parses local penguin slash commands", () => {
    expect(parsePenguinPromptCommand("/config")).toEqual({
      name: "config",
      known: true,
      keepDialog: true,
    })
    expect(parsePenguinPromptCommand("/thinking extra")).toEqual({
      name: "thinking",
      known: true,
      keepDialog: false,
    })
    expect(parsePenguinPromptCommand("/unknown")).toEqual({
      name: "unknown",
      known: false,
      keepDialog: false,
    })
  })

  test("builds optimistic penguin message, part, and busy events", () => {
    const events = createOptimisticPenguinEvents({
      sessionID: "ses_123",
      messageID: "msg_123",
      partID: "part_123",
      inputText: "hello world",
      agentName: "build",
      providerID: "openai",
      modelID: "gpt-5",
      now: 123,
    })

    expect(events.message.properties.info).toEqual({
      id: "msg_123",
      sessionID: "ses_123",
      role: "user",
      time: {
        created: 123,
      },
      agent: "build",
      model: {
        providerID: "openai",
        modelID: "gpt-5",
      },
    })
    expect(events.part.properties.part).toEqual({
      id: "part_123",
      sessionID: "ses_123",
      messageID: "msg_123",
      type: "text",
      text: "hello world",
      time: {
        start: 123,
        end: 123,
      },
    })
    expect(events.status.properties).toEqual({
      sessionID: "ses_123",
      status: {
        type: "busy",
      },
    })
  })

  test("creates a penguin session from wrapped responses", async () => {
    const sessionID = await createPenguinSession({
      fetch: async () => new Response(JSON.stringify({ data: { id: "ses_created" } }), { status: 200 }),
      url: "http://localhost:9000",
      directory: "/workspace/app",
      agentMode: "build",
      providerID: "openai",
      modelID: "gpt-5",
      variant: "fast",
    })

    expect(sessionID).toBe("ses_created")
  })
})
