import { describe, expect, test } from "bun:test"

import { terminalFocusFromInput } from "../../../src/cli/cmd/tui/context/terminal-focus-state"

describe("terminal focus tracking", () => {
  test("marks focus reporting supported after focus events", () => {
    expect(
      terminalFocusFromInput("\x1b[O", {
        focused: true,
        supported: false,
      }),
    ).toEqual({
      focused: false,
      supported: true,
    })

    expect(
      terminalFocusFromInput("\x1b[I", {
        focused: false,
        supported: true,
      }),
    ).toEqual({
      focused: true,
      supported: true,
    })
  })

  test("leaves unrelated input unchanged", () => {
    const current = {
      focused: true,
      supported: false,
    }

    expect(terminalFocusFromInput("abc", current)).toEqual(current)
  })
})
