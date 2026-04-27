import { describe, expect, test } from "bun:test"
import type { Message, Part, Session } from "@opencode-ai/sdk/v2"
import {
  hydrateSessionSnapshot,
  mergeHydratedMessages,
  type SessionHydrationClient,
  upsertPenguinMessage,
} from "../../../src/cli/cmd/tui/context/session-hydration"

const session: Session = {
  id: "ses_reopen",
  slug: "ses_reopen",
  projectID: "penguin",
  directory: "/tmp/project",
  title: "Reopen Session",
  version: "0.0.0",
  time: {
    created: 1000,
    updated: 2000,
  },
}

const user: Message = {
  id: "msg_user_1",
  sessionID: "ses_reopen",
  role: "user",
  agent: "build",
  model: { providerID: "openrouter", modelID: "openai/gpt-5-mini" },
  time: { created: 1000 },
}

const assistant: Message = {
  id: "msg_assistant_1",
  sessionID: "ses_reopen",
  role: "assistant",
  agent: "build",
  modelID: "openai/gpt-5-mini",
  providerID: "openrouter",
  mode: "",
  parentID: "root",
  path: { cwd: "/tmp/project", root: "/tmp/project" },
  cost: 0,
  tokens: { input: 10, output: 20, reasoning: 0, cache: { read: 0, write: 0 } },
  time: { created: 1001, completed: 1002 },
}

const parts: Part[] = [
  {
    id: "part_1",
    sessionID: "ses_reopen",
    messageID: "msg_user_1",
    type: "text",
    text: "hello",
  },
]

describe("sync hydration", () => {
  test("returns full session history for reopen", async () => {
    const rows = [
      { info: user, parts },
      {
        info: assistant,
        parts: [
          {
            id: "part_2",
            sessionID: "ses_reopen",
            messageID: "msg_assistant_1",
            type: "text" as const,
            text: "hi",
          },
        ],
      },
    ]

    const client: SessionHydrationClient = {
      session: {
        get: async () => ({ data: session }),
        messages: async () => ({ data: rows }),
        todo: async () => ({ data: [] }),
        diff: async () => ({ data: [] }),
      },
    }

    const result = await hydrateSessionSnapshot(client, "ses_reopen")

    expect(result.session.id).toBe("ses_reopen")
    expect(result.messages.length).toBe(2)
    expect(result.messages[0].info.id).toBe("msg_user_1")
    expect(result.messages[1].info.id).toBe("msg_assistant_1")
  })

  test("falls back when optional endpoints fail", async () => {
    const client: SessionHydrationClient = {
      session: {
        get: async () => ({ data: session }),
        messages: async () => ({ data: [{ info: user, parts }] }),
        todo: async () => Promise.reject(new Error("todo unavailable")),
        diff: async () => Promise.reject(new Error("diff unavailable")),
      },
    }

    const result = await hydrateSessionSnapshot(client, "ses_reopen")

    expect(result.messages.length).toBe(1)
    expect(result.todo).toEqual([])
    expect(result.diff).toEqual([])
  })

  test("handles clients without optional methods", async () => {
    const client: SessionHydrationClient = {
      session: {
        get: async () => ({ data: session }),
        messages: async () => ({ data: [{ info: user, parts }] }),
      },
    }

    const result = await hydrateSessionSnapshot(client, "ses_reopen")

    expect(result.messages.length).toBe(1)
    expect(result.todo).toEqual([])
    expect(result.diff).toEqual([])
  })

  test("uses fallback session when session.get fails", async () => {
    const client: SessionHydrationClient = {
      session: {
        get: async () => Promise.reject(new Error("not found")),
        messages: async () => ({ data: [{ info: user, parts }] }),
      },
    }

    const result = await hydrateSessionSnapshot(client, "ses_reopen", {
      fallbackSession: session,
    })

    expect(result.session.id).toBe("ses_reopen")
    expect(result.messages.length).toBe(1)
  })

  test("preserves child session lineage when hydrating a reopened session", async () => {
    const child = {
      ...session,
      id: "ses_child",
      slug: "ses_child",
      title: "Child Session",
      parentID: "ses_parent",
    }
    const client: SessionHydrationClient = {
      session: {
        get: async () => ({ data: child }),
        messages: async () => ({ data: [{ info: user, parts }] }),
      },
    }

    const result = await hydrateSessionSnapshot(client, "ses_child")

    expect(result.session.id).toBe("ses_child")
    expect(result.session.parentID).toBe("ses_parent")
  })

  test("throws when session is missing and no fallback exists", async () => {
    const client: SessionHydrationClient = {
      session: {
        get: async () => Promise.reject(new Error("not found")),
        messages: async () => ({ data: [] }),
      },
    }

    await expect(hydrateSessionSnapshot(client, "ses_missing")).rejects.toThrow("Session ses_missing not found")
  })

  test("preserves optimistic user message when hydration is empty", () => {
    const optimistic: Message = {
      id: "msg_local_1",
      sessionID: "ses_reopen",
      role: "user",
      agent: "build",
      model: { providerID: "openrouter", modelID: "openai/gpt-5-mini" },
      time: { created: 10_000 },
    }
    const optimisticParts: Part[] = [
      {
        id: "part_local_1",
        sessionID: "ses_reopen",
        messageID: "msg_local_1",
        type: "text",
        text: "first prompt",
      },
    ]

    const merged = mergeHydratedMessages([optimistic], [], { [optimistic.id]: optimisticParts })

    expect(merged).toHaveLength(1)
    expect(merged[0]?.id).toBe("msg_local_1")
  })

  test("drops optimistic duplicate when hydrated user message is equivalent", () => {
    const optimistic: Message = {
      id: "msg_local_1",
      sessionID: "ses_reopen",
      role: "user",
      agent: "build",
      model: { providerID: "openrouter", modelID: "openai/gpt-5-mini" },
      time: { created: 10_000 },
    }
    const optimisticParts: Part[] = [
      {
        id: "part_local_1",
        sessionID: "ses_reopen",
        messageID: "msg_local_1",
        type: "text",
        text: "first prompt",
      },
    ]
    const hydratedUser: Message = {
      id: "msg_server_1",
      sessionID: "ses_reopen",
      role: "user",
      agent: "build",
      model: { providerID: "openrouter", modelID: "openai/gpt-5-mini" },
      time: { created: 10_020 },
    }
    const hydratedParts: Part[] = [
      {
        id: "part_server_1",
        sessionID: "ses_reopen",
        messageID: "msg_server_1",
        type: "text",
        text: "first prompt",
      },
    ]

    const merged = mergeHydratedMessages([optimistic], [{ info: hydratedUser, parts: hydratedParts }], {
      [optimistic.id]: optimisticParts,
    })

    expect(merged).toHaveLength(1)
    expect(merged[0]?.id).toBe("msg_server_1")
  })

  test("keeps repeated prompt text when timestamps are far apart", () => {
    const optimistic: Message = {
      id: "msg_local_2",
      sessionID: "ses_reopen",
      role: "user",
      agent: "build",
      model: { providerID: "openrouter", modelID: "openai/gpt-5-mini" },
      time: { created: 100_000 },
    }
    const optimisticParts: Part[] = [
      {
        id: "part_local_2",
        sessionID: "ses_reopen",
        messageID: "msg_local_2",
        type: "text",
        text: "same text",
      },
    ]
    const hydratedUser: Message = {
      id: "msg_server_old",
      sessionID: "ses_reopen",
      role: "user",
      agent: "build",
      model: { providerID: "openrouter", modelID: "openai/gpt-5-mini" },
      time: { created: 1_000 },
    }
    const hydratedParts: Part[] = [
      {
        id: "part_server_old",
        sessionID: "ses_reopen",
        messageID: "msg_server_old",
        type: "text",
        text: "same text",
      },
    ]

    const merged = mergeHydratedMessages([optimistic], [{ info: hydratedUser, parts: hydratedParts }], {
      [optimistic.id]: optimisticParts,
    })

    expect(merged).toHaveLength(2)
    expect(merged.map((item) => item.id)).toEqual(["msg_server_old", "msg_local_2"])
  })

  test("preserves hydrated transcript order even when timestamps disagree", () => {
    const hydratedUser: Message = {
      ...user,
      id: "msg_user_skewed",
      time: { created: 20 },
    }
    const hydratedAssistant: Message = {
      ...assistant,
      id: "msg_assistant_skewed",
      time: { created: 10, completed: 11 },
    }

    const merged = mergeHydratedMessages(
      undefined,
      [
        { info: hydratedUser, parts },
        { info: hydratedAssistant, parts: [] },
      ],
      {},
    )

    expect(merged.map((item) => item.id)).toEqual([
      "msg_user_skewed",
      "msg_assistant_skewed",
    ])
  })

  test("orders new live penguin messages by creation time", () => {
    const optimistic = {
      ...user,
      id: "msg_local_user",
      time: { created: 20 },
    }
    const streamed = {
      ...assistant,
      id: "msg_streamed_assistant",
      time: { created: 10, completed: 11 },
    }

    const merged = upsertPenguinMessage([optimistic], streamed)

    expect(merged.map((item) => item.id)).toEqual([
      "msg_streamed_assistant",
      "msg_local_user",
    ])
  })

  test("inserts late optimistic user before newer streamed tool response", () => {
    const firstUser = {
      ...user,
      time: { created: 5 },
    }
    const firstAssistant = {
      ...assistant,
      id: "msg_first_assistant",
      time: { created: 10, completed: 11 },
    }
    const toolAssistant = {
      ...assistant,
      id: "msg_tool_assistant",
      time: { created: 30, completed: 40 },
    }
    const lateUser = {
      ...user,
      id: "msg_late_user",
      time: { created: 20 },
    }

    const merged = upsertPenguinMessage([firstUser, firstAssistant, toolAssistant], lateUser)

    expect(merged.map((item) => item.id)).toEqual([
      "msg_user_1",
      "msg_first_assistant",
      "msg_late_user",
      "msg_tool_assistant",
    ])
  })

  test("replaces existing live penguin messages in place", () => {
    const first = {
      ...assistant,
      id: "msg_streamed_assistant",
      time: { created: 10 },
    }
    const updated = {
      ...first,
      time: { created: 10, completed: 11 },
    }

    const merged = upsertPenguinMessage([user, first], updated)

    expect(merged).toEqual([user, updated])
  })
})
