import { afterEach, beforeEach, describe, expect, spyOn, test } from "bun:test"
import {
  fetchBootstrapJson,
  mapPenguinBootstrap,
  PenguinSessionArraySchema,
  parsePenguinUsage,
  unwrapBootstrapData,
} from "../../../src/cli/cmd/tui/context/sync-bootstrap"
import { Log } from "../../../src/util/log"

describe("sync bootstrap", () => {
  let warn: ReturnType<typeof spyOn>

  beforeEach(() => {
    warn = spyOn(Log.Default, "warn").mockImplementation(() => {})
  })

  afterEach(() => {
    warn.mockRestore()
  })

  test("returns parsed bootstrap json on success", async () => {
    const result = await fetchBootstrapJson({
      fetch: async () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
      path: "http://localhost/config",
      endpoint: "/config",
      fallback: undefined as { ok: boolean } | undefined,
    })

    expect(result).toEqual({ ok: true })
    expect(warn).not.toHaveBeenCalled()
  })

  test("degrades to fallback on non-2xx bootstrap response", async () => {
    const fallback = { share: "disabled" }
    const result = await fetchBootstrapJson({
      fetch: async () => new Response("unauthorized", { status: 401 }),
      path: "http://localhost/config",
      endpoint: "/config",
      fallback,
    })

    expect(result).toBe(fallback)
    expect(warn).toHaveBeenCalledTimes(1)
  })

  test("throws for required bootstrap failures", async () => {
    await expect(
      fetchBootstrapJson({
        fetch: async () => {
          throw new Error("network down")
        },
        path: "http://localhost/config",
        endpoint: "/config",
        fallback: undefined,
        required: true,
      }),
    ).rejects.toThrow("network down")

    expect(warn).not.toHaveBeenCalled()
  })

  test("unwraps OpenCode-style data envelopes only when they are wrappers", () => {
    expect(unwrapBootstrapData({ data: { ok: true } })).toEqual({ ok: true })
    expect(unwrapBootstrapData({ data: { ok: true }, meta: { cursor: null } })).toEqual({ ok: true })
    expect(unwrapBootstrapData({ data: { ok: true }, other: true })).toEqual({
      data: { ok: true },
      other: true,
    })
  })

  test("parses Penguin usage payloads with defaults", () => {
    expect(
      parsePenguinUsage({
        usage: {
          current_total_tokens: 1200,
          available_tokens: 800,
          percentage: 12,
          truncations: {
            total_truncations: 2,
            messages_removed: 3,
            tokens_freed: 400,
          },
        },
      }),
    ).toEqual({
      current_total_tokens: 1200,
      max_context_window_tokens: null,
      available_tokens: 800,
      percentage: 12,
      truncations: {
        total_truncations: 2,
        messages_removed: 3,
        tokens_freed: 400,
      },
    })
    expect(parsePenguinUsage({ usage: {} })).toBeUndefined()
  })

  test("validates Penguin session list payloads", () => {
    expect(
      PenguinSessionArraySchema.safeParse([
        {
          id: "ses_1",
          title: "Mapped Session",
          time: {
            created: 100,
            updated: 200,
          },
          display_message_count: 1,
          fallback_title: false,
        },
      ]).success,
    ).toBe(true)

    expect(
      PenguinSessionArraySchema.safeParse([
        {
          id: "ses_1",
          title: "Missing Time",
        },
      ]).success,
    ).toBe(false)
  })

  test("maps Penguin bootstrap responses into TUI store state", () => {
    const result = mapPenguinBootstrap({
      baseUrl: "http://127.0.0.1:9000",
      directory: "/tmp/project",
      now: 1000,
      providersData: {
        data: {
          providers: [
            {
              id: "openai",
              name: "OpenAI",
              source: "custom",
              env: [],
              options: {},
              models: {},
            },
          ],
          default: {
            openai: "gpt-5.5",
          },
        },
      },
      providerListData: undefined,
      configData: { data: { share: "disabled", service_tier: "priority" } },
      providerAuthData: { data: { openai: [{ type: "oauth", label: "OpenAI OAuth" }] } },
      sessions: [
        {
          id: "ses_1",
          title: "Mapped Session",
          created_at: "2026-05-27T00:00:00.000Z",
          last_active: "2026-05-27T00:01:00.000Z",
          directory: "/tmp/project",
          agent_mode: "build",
          providerID: "openai",
          modelID: "gpt-5.5",
          message_count: 0,
          display_message_count: 0,
          fallback_title: false,
          usage: {
            current_total_tokens: 42,
            max_context_window_tokens: 100,
            available_tokens: 58,
          },
        },
      ],
      roster: [
        {
          id: "default",
          agent_mode: "build",
          is_sub_agent: false,
          options: {},
        },
      ],
    })

    expect(result.provider.map((item) => item.id)).toEqual(["openai"])
    expect(result.provider_default).toEqual({ openai: "gpt-5.5" })
    expect(result.provider_next.connected).toEqual(["penguin"])
    expect(result.provider_auth).toEqual({ openai: [{ type: "oauth", label: "OpenAI OAuth" }] })
    expect(result.config).toMatchObject({ share: "disabled", service_tier: "priority" })
    expect(result.session[0]).toMatchObject({
      id: "ses_1",
      title: "Mapped Session",
      directory: "/tmp/project",
      agent_mode: "build",
      providerID: "openai",
      modelID: "gpt-5.5",
      message_count: 0,
      display_message_count: 0,
      fallback_title: false,
    })
    expect(result.session_usage.ses_1?.current_total_tokens).toBe(42)
    expect(result.session_status.ses_1).toEqual({ type: "idle" })
    expect(result.agent[0]?.name).toBe("default")
    expect(result.agent[0]?.options).toMatchObject({ agent_mode: "build" })
    expect(result.command.map((item) => item.name)).toEqual(["config", "tool_details", "thinking"])
  })

  test("uses fallback provider, config, and agent when bootstrap responses are sparse", () => {
    const result = mapPenguinBootstrap({
      baseUrl: "http://127.0.0.1:9000",
      directory: "/tmp/project",
      now: 1000,
      providersData: undefined,
      providerListData: undefined,
      configData: undefined,
      providerAuthData: undefined,
      sessions: [],
      roster: [],
    })

    expect(result.provider[0]?.id).toBe("penguin")
    expect(result.provider_default).toEqual({ penguin: "penguin-default" })
    expect(result.provider_next.connected).toEqual(["penguin"])
    expect(result.config).toEqual({ share: "disabled" })
    expect(result.agent).toEqual([
      {
        name: "penguin",
        mode: "primary",
        permission: [],
        options: {},
      },
    ])
    expect(result.path.directory).toBe("/tmp/project")
  })
})
