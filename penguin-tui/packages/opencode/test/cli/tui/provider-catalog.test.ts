import { describe, expect, test } from "bun:test"

import { mergeProviderCatalogs } from "../../../src/cli/cmd/tui/util/provider-catalog"

describe("provider catalog merge", () => {
  test("keeps full provider-list models when configured providers are sparse", () => {
    const merged = mergeProviderCatalogs(
      [
        {
          id: "openrouter",
          name: "OpenRouter",
          models: {
            "anthropic/claude-sonnet-4.5": {
              id: "anthropic/claude-sonnet-4.5",
              name: "sonnet-4.5",
              status: "active",
              capabilities: {
                reasoning: false,
              },
            },
          },
        },
      ],
      [
        {
          id: "openrouter",
          name: "OpenRouter",
          models: {
            "anthropic/claude-sonnet-4.5": {
              id: "anthropic/claude-sonnet-4.5",
              name: "Claude Sonnet 4.5",
              reasoning: true,
            },
            "moonshotai/kimi-k2.7-code": {
              id: "moonshotai/kimi-k2.7-code",
              name: "MoonshotAI: Kimi K2.7 Code",
              reasoning: true,
            },
            "nvidia/nemotron-3-ultra": {
              id: "nvidia/nemotron-3-ultra",
              name: "NVIDIA: Nemotron 3 Ultra",
            },
          },
        },
      ],
    )

    const openrouter = merged.find((provider) => provider.id === "openrouter")
    expect(Object.keys(openrouter?.models ?? {})).toEqual([
      "anthropic/claude-sonnet-4.5",
      "moonshotai/kimi-k2.7-code",
      "nvidia/nemotron-3-ultra",
    ])
    expect(openrouter?.models?.["anthropic/claude-sonnet-4.5"]?.name).toBe("sonnet-4.5")
    expect(openrouter?.models?.["moonshotai/kimi-k2.7-code"]?.capabilities?.reasoning).toBe(true)
  })

  test("adds providers that only exist in the provider-list catalog", () => {
    const merged = mergeProviderCatalogs([], [
      {
        id: "anthropic",
        name: "Anthropic",
        models: {
          "claude-opus-4": {
            id: "claude-opus-4",
            name: "Claude Opus 4",
          },
        },
      },
    ])

    expect(merged).toHaveLength(1)
    expect(merged[0]).toMatchObject({
      id: "anthropic",
      name: "Anthropic",
    })
    expect(merged[0]?.models?.["claude-opus-4"]?.providerID).toBe("anthropic")
  })
})
