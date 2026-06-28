import { describe, expect, test } from "bun:test"

import { nextVariantSelection } from "../../../src/cli/cmd/tui/context/variant-cycle"

describe("variant cycling", () => {
  test("reports unavailable when the current model has no variants", () => {
    expect(nextVariantSelection([], undefined)).toEqual({ type: "unavailable" })
  })

  test("selects the first variant when none is active", () => {
    expect(nextVariantSelection(["low", "high"], undefined)).toEqual({
      type: "selected",
      variant: "low",
    })
  })

  test("advances to the next variant", () => {
    expect(nextVariantSelection(["low", "high"], "low")).toEqual({
      type: "selected",
      variant: "high",
    })
  })

  test("clears the variant after the final or stale value", () => {
    expect(nextVariantSelection(["low", "high"], "high")).toEqual({
      type: "selected",
      variant: undefined,
    })
    expect(nextVariantSelection(["low", "high"], "stale")).toEqual({
      type: "selected",
      variant: undefined,
    })
  })
})
