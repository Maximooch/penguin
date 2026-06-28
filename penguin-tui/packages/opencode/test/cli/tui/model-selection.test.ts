import { describe, expect, test } from "bun:test"

import { isCatalogModelValid, resolveCatalogModel } from "../../../src/cli/cmd/tui/util/model-selection"

const providers = [
  {
    id: "openai",
    models: {
      "gpt-5.5": {
        id: "gpt-5.5",
        name: "GPT-5.5",
      },
      "gpt-5.5-mini": {
        id: "gpt-5.5-mini",
        name: "GPT-5.5 Mini",
      },
    },
  },
]

describe("model selection", () => {
  test("preserves exact catalog ids", () => {
    expect(resolveCatalogModel(providers, { providerID: "openai", modelID: "gpt-5.5" })).toEqual({
      providerID: "openai",
      modelID: "gpt-5.5",
    })
  })

  test("resolves display-name model ids back to catalog ids", () => {
    expect(resolveCatalogModel(providers, { providerID: "openai", modelID: "GPT-5.5" })).toEqual({
      providerID: "openai",
      modelID: "gpt-5.5",
    })
  })

  test("rejects unknown models", () => {
    expect(resolveCatalogModel(providers, { providerID: "openai", modelID: "not-real" })).toBeUndefined()
    expect(isCatalogModelValid(providers, { providerID: "openai", modelID: "not-real" })).toBe(false)
  })
})
