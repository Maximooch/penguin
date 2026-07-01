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

  test("prefers backend sparse catalog metadata over local model counts", () => {
    const emptyButRefreshing = [
      {
        id: "openrouter",
        catalog: {
          model_count: 0,
          sparse: true,
          state: "empty",
        },
        models: {},
      },
    ]
    const readyWithFewConfiguredAliases = [
      {
        id: "openrouter",
        catalog: {
          model_count: 3,
          sparse: false,
          state: "ready",
        },
        models: {
          "haiku-4.5": { id: "haiku-4.5", name: "haiku-4.5" },
          "opus-4.5": { id: "opus-4.5", name: "opus-4.5" },
          "sonnet-4.5": { id: "sonnet-4.5", name: "sonnet-4.5" },
        },
      },
    ]

    expect(hasSparseModelCatalog(emptyButRefreshing)).toBe(true)
    expect(hasSparseModelCatalog(readyWithFewConfiguredAliases)).toBe(false)
  })

  test("merges warmed provider list models into sparse configured providers", () => {
    const configuredProviders = [
      {
        catalog: {
          model_count: 1,
          sparse: true,
          state: "sparse",
        },
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
        catalog: {
          model_count: 24,
          sparse: false,
          state: "ready",
        },
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
    expect(openrouter!.catalog).toEqual({
      model_count: 24,
      sparse: false,
      state: "ready",
    })
    expect(Object.keys(openrouter!.models)).toHaveLength(25)
    expect(openrouter!.models["haiku-4.5"]?.capabilities.reasoning).toBe(true)
    expect(openrouter!.models["vendor/model-0"]?.capabilities.reasoning).toBe(true)
    expect(hasSparseModelCatalog(catalog)).toBe(false)
  })

  test("preserves live sparse provider metadata when model counts match", () => {
    const catalog = createModelCatalogProviders(
      [
        {
          catalog: {
            model_count: 1,
            sparse: false,
            state: "ready",
          },
          id: "openrouter",
          name: "OpenRouter",
          models: {
            "haiku-4.5": { id: "haiku-4.5", name: "haiku-4.5" },
          },
        },
      ],
      [
        {
          catalog: {
            model_count: 1,
            sparse: true,
            state: "sparse",
          },
          id: "openrouter",
          name: "OpenRouter",
          models: {
            "haiku-4.5": { id: "haiku-4.5", name: "haiku-4.5" },
          },
        },
      ],
    )

    expect(catalog[0]?.catalog).toEqual({
      model_count: 1,
      sparse: true,
      state: "sparse",
    })
    expect(hasSparseModelCatalog(catalog)).toBe(true)
  })

  test("deep-merges overlapping warmed and configured model metadata", () => {
    const catalog = createModelCatalogProviders(
      [
        {
          id: "openrouter",
          name: "OpenRouter",
          models: {
            "vendor/model-0": {
              id: "vendor/model-0",
              name: "Configured Alias",
              status: "active",
              capabilities: {
                attachment: false,
                reasoning: false,
                temperature: true,
                toolcall: false,
              },
              options: { effort: "high" },
            },
          },
        },
      ],
      [
        {
          id: "openrouter",
          name: "OpenRouter",
          models: {
            "vendor/model-0": {
              id: "vendor/model-0",
              name: "Warmed Name",
              release_date: "2026-06-01",
              status: "active",
              capabilities: {
                attachment: true,
                reasoning: true,
                temperature: false,
                toolcall: true,
              },
              variants: { default: { id: "vendor/model-0" } },
            },
          },
        },
      ],
    )

    const model = catalog[0]?.models["vendor/model-0"]

    expect(model?.name).toBe("Configured Alias")
    expect(model?.release_date).toBe("2026-06-01")
    expect(model?.capabilities).toEqual({
      attachment: true,
      reasoning: true,
      temperature: true,
      toolcall: true,
    })
    expect(model?.variants).toEqual({ default: { id: "vendor/model-0" } })
    expect(model?.options).toEqual({ effort: "high" })
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
