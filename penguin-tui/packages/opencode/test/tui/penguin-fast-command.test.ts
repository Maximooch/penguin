import { describe, expect, test } from "bun:test"
import {
  applyPenguinFastCommand,
  formatPenguinFastModeStatus,
} from "../../src/cli/cmd/tui/component/prompt/penguin-fast-command"

function fastMode(initial = false) {
  let value = initial
  return {
    controller: {
      enabled: () => value,
      set: (next: boolean | undefined) => {
        value = next ?? false
      },
      toggle: () => {
        value = !value
      },
    },
    value: () => value,
  }
}

describe("Penguin fast command", () => {
  test("ignores non-fast prompts", () => {
    const fast = fastMode(false)

    expect(
      applyPenguinFastCommand({
        fast: fast.controller,
        text: "hello",
      }),
    ).toEqual({ matched: false })
    expect(fast.value()).toBe(false)
  })

  test("toggles fast mode with /fast", () => {
    const fast = fastMode(false)

    expect(
      applyPenguinFastCommand({
        fast: fast.controller,
        text: "/fast",
      }),
    ).toEqual({
      matched: true,
      message: "Fast mode on",
      variant: "info",
    })
    expect(fast.value()).toBe(true)
  })

  test("sets explicit fast mode values", () => {
    const fast = fastMode(false)

    expect(applyPenguinFastCommand({ fast: fast.controller, text: "/fast on" })).toMatchObject({
      message: "Fast mode on",
      variant: "info",
    })
    expect(fast.value()).toBe(true)

    expect(applyPenguinFastCommand({ fast: fast.controller, text: "/fast off" })).toMatchObject({
      message: "Fast mode off",
      variant: "info",
    })
    expect(fast.value()).toBe(false)
  })

  test("reports status without changing fast mode", () => {
    const fast = fastMode(true)

    expect(applyPenguinFastCommand({ fast: fast.controller, text: "/fast status" })).toEqual({
      matched: true,
      message: "Fast mode on",
      variant: "info",
    })
    expect(fast.value()).toBe(true)
  })

  test("warns on invalid fast mode arguments", () => {
    const fast = fastMode(false)

    expect(applyPenguinFastCommand({ fast: fast.controller, text: "/fast turbo" })).toEqual({
      matched: true,
      message: "Usage: /fast [on|off|status]",
      variant: "warning",
    })
    expect(fast.value()).toBe(false)
  })

  test("formats visible fast mode status", () => {
    expect(formatPenguinFastModeStatus(true)).toBe("Fast mode on")
    expect(formatPenguinFastModeStatus(false)).toBe("Fast mode off")
  })
})
