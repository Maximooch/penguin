import { describe, expect, test } from "bun:test"
import { createPenguinPromptSubmitGate } from "../../src/cli/cmd/tui/component/prompt/penguin-submit-gate"

describe("Penguin prompt submit gate", () => {
  test("blocks duplicate submits until the active submit releases", () => {
    const gate = createPenguinPromptSubmitGate()

    const release = gate.tryStart()

    expect(release).toBeFunction()
    expect(gate.active).toBe(true)
    expect(gate.tryStart()).toBeUndefined()

    release?.()

    expect(gate.active).toBe(false)
    expect(gate.tryStart()).toBeFunction()
  })

  test("release is idempotent", () => {
    const gate = createPenguinPromptSubmitGate()
    const release = gate.tryStart()

    release?.()
    release?.()

    expect(gate.active).toBe(false)
  })

  test("stale releases do not unlock newer submits", () => {
    const gate = createPenguinPromptSubmitGate()
    const stale = gate.tryStart()

    stale?.()
    const current = gate.tryStart()
    stale?.()

    expect(gate.active).toBe(true)

    current?.()

    expect(gate.active).toBe(false)
  })
})
