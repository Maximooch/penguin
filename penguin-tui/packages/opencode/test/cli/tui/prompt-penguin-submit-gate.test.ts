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
