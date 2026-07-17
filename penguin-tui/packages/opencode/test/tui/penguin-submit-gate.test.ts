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

  test("expires and releases a stuck submit deterministically", () => {
    const callbacks: Array<() => void> = []
    const gate = createPenguinPromptSubmitGate({
      schedule: (callback) => {
        callbacks.push(callback)
        return () => {}
      },
    })
    let expired = false

    const release = gate.tryStart({
      onTimeout: () => {
        expired = true
      },
      timeoutMs: 35 * 60 * 1000,
    })

    expect(gate.active).toBe(true)
    expect(callbacks).toHaveLength(1)
    callbacks[0]()
    expect(expired).toBe(true)
    expect(gate.active).toBe(false)

    const next = gate.tryStart()
    expect(next).toBeFunction()
    release?.()
    expect(gate.active).toBe(true)
    next?.()
  })
})
