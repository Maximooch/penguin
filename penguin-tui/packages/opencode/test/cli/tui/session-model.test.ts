import { describe, expect, test } from "bun:test"

import { hydratedSessionModel, hydratedSessionVariant } from "../../../src/cli/cmd/tui/util/session-model"

describe("session model hydration", () => {
  test("uses explicit session-scoped backend model selections", () => {
    const session = {
      providerID: "openai",
      modelID: "gpt-5.5",
      variant: "high",
      modelSelection: {
        providerID: "openrouter",
        modelID: "z-ai/glm-5.2",
        variant: "fast",
        sessionScoped: true,
        source: "session",
      },
    }

    expect(hydratedSessionModel(session)).toEqual({
      providerID: "openrouter",
      modelID: "z-ai/glm-5.2",
    })
    expect(hydratedSessionVariant(session)).toBe("fast")
  })

  test("ignores backend global fallbacks when switching sessions", () => {
    const session = {
      providerID: "openai",
      modelID: "gpt-5.5",
      modelSelection: {
        providerID: "openai",
        modelID: "gpt-5.5",
        sessionScoped: false,
        source: "global",
      },
    }

    expect(hydratedSessionModel(session)).toBeUndefined()
    expect(hydratedSessionVariant(session)).toBeUndefined()
  })

  test("keeps legacy top-level session model support for older backends", () => {
    expect(
      hydratedSessionModel({
        providerID: "openrouter",
        modelID: "moonshotai/kimi-k2.7-code",
        variant: "low",
      }),
    ).toEqual({
      providerID: "openrouter",
      modelID: "moonshotai/kimi-k2.7-code",
    })
    expect(
      hydratedSessionVariant({
        providerID: "openrouter",
        modelID: "moonshotai/kimi-k2.7-code",
        variant: "low",
      }),
    ).toBe("low")
  })
})
