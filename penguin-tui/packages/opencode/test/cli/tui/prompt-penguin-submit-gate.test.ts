import { describe, expect, test } from "bun:test"
import {
  createPenguinPromptSubmitGate,
  tryStartPenguinPromptSubmit,
} from "../../../src/cli/cmd/tui/component/prompt/penguin-submit-gate"

describe("penguin prompt submit gate", () => {
  test("blocks a new submit while the session is still busy", () => {
    const gate = createPenguinPromptSubmitGate()

    const result = tryStartPenguinPromptSubmit({
      busy: true,
      gate,
    })

    expect(result).toEqual({
      ok: false,
      reason: "busy",
    })
    expect(gate.active).toBe(false)
  })

  test("allows a control command while busy without allowing duplicates", () => {
    const primaryGate = createPenguinPromptSubmitGate()
    const controlGate = createPenguinPromptSubmitGate()
    const releasePrimary = primaryGate.tryStart()

    const first = tryStartPenguinPromptSubmit({
      busy: true,
      gate: controlGate,
      allowWhileBusy: true,
    })
    const second = tryStartPenguinPromptSubmit({
      busy: true,
      gate: controlGate,
      allowWhileBusy: true,
    })

    expect(primaryGate.active).toBe(true)
    expect(first.ok).toBe(true)
    expect(second).toEqual({ ok: false, reason: "submitting" })
    if (first.ok) first.release()
    releasePrimary?.()
    expect(primaryGate.active).toBe(false)
    expect(controlGate.active).toBe(false)
  })

  test("blocks duplicate submits until the active send releases", () => {
    const gate = createPenguinPromptSubmitGate()

    const first = tryStartPenguinPromptSubmit({
      busy: false,
      gate,
    })
    const second = tryStartPenguinPromptSubmit({
      busy: false,
      gate,
    })

    expect(first.ok).toBe(true)
    expect(second).toEqual({
      ok: false,
      reason: "submitting",
    })

    if (first.ok) first.release()

    const third = tryStartPenguinPromptSubmit({
      busy: false,
      gate,
    })

    expect(third.ok).toBe(true)
    if (third.ok) third.release()
  })
})
