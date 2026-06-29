import { describe, expect, test } from "bun:test"
import {
  createModelCatalogProviders,
  hasSparseModelCatalog,
  modelCatalogCount,
} from "../../../src/cli/cmd/tui/util/model-catalog"
import { resolveCatalogModel } from "../../../src/cli/cmd/tui/util/model-selection"

describe("model catalog", () => {
  test("detects cold sparse Penguin model catalogs", () => {
    const coldCatalog = [
      {
        id: "openai",
        models: {
          "gpt-5.5": { id: "gpt-5.5", name: "GPT-5.5" },
        },
      },
      {
        id: "openrouter",
        models: {
          "haiku-4.5": { id: "haiku-4.5", name: "haiku-4.5" },
          "opus-4.5": { id: "opus-4.5", name: "opus-4.5" },
          "sonnet-4.5": { id: "sonnet-4.5", name: "sonnet-4.5" },
        },
      },
    ]

    expect(modelCatalogCount(coldCatalog)).toBe(4)
    expect(hasSparseModelCatalog(coldCatalog)).toBe(true)
  })

  test("merges warmed provider list models into sparse configured providers", () => {
    const configuredProviders = [
      {
        id: "openrouter",
        name: "OpenRouter",
        env: ["OPENROUTER_API_KEY"],
        models: {
          "haiku-4.5": {
            id: "haiku-4.5",
            name: "haiku-4.5",
            providerID: "openrouter",
            status: "active",
            capabilities: {
              reasoning: true,
              attachment: false,
              temperature: true,
              toolcall: true,
            },
          },
        },
      },
    ]
    const warmedProviders = [
      {
        id: "openrouter",
        name: "OpenRouter",
        models: Object.fromEntries(
          Array.from({ length: 24 }, (_, index) => [
            `vendor/model-${index}`,
            {
              id: `vendor/model-${index}`,
              name: `Vendor Model ${index}`,
              status: "active",
              reasoning: index % 2 === 0,
              tool_call: true,
            },
          ]),
        ),
      },
    ]

    const catalog = createModelCatalogProviders(configuredProviders, warmedProviders)
    const openrouter = catalog.find((provider) => provider.id === "openrouter")

    expect(openrouter).toBeDefined()
    expect(Object.keys(openrouter!.models)).toHaveLength(25)
    expect(openrouter!.models["haiku-4.5"]?.capabilities.reasoning).toBe(true)
    expect(openrouter!.models["vendor/model-0"]?.capabilities.reasoning).toBe(true)
    expect(hasSparseModelCatalog(catalog)).toBe(false)
  })

  test("validates model selections against warmed catalog models", () => {
    const catalog = createModelCatalogProviders(
      [
        {
          id: "openrouter",
          name: "OpenRouter",
          models: {
            "haiku-4.5": { id: "haiku-4.5", name: "haiku-4.5" },
          },
        },
      ],
      [
        {
          id: "openrouter",
          name: "OpenRouter",
          models: {
            "moonshotai/kimi-k2.7-code": {
              id: "moonshotai/kimi-k2.7-code",
              name: "MoonshotAI: Kimi K2.7 Code",
              status: "active",
            },
          },
        },
      ],
    )

    expect(
      resolveCatalogModel(catalog, {
        providerID: "openrouter",
        modelID: "moonshotai/kimi-k2.7-code",
      }),
    ).toEqual({
      providerID: "openrouter",
      modelID: "moonshotai/kimi-k2.7-code",
    })
  })
})
