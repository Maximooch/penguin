const FOCUS_IN = "\x1b[I"
const FOCUS_OUT = "\x1b[O"

export const ENABLE_FOCUS_REPORTING = "\x1b[?1004h"
export const DISABLE_FOCUS_REPORTING = "\x1b[?1004l"

export type TerminalFocusState = {
  focused: boolean
  supported: boolean
}

export function terminalFocusFromInput(input: Buffer | string, current: TerminalFocusState): TerminalFocusState {
  const text = Buffer.isBuffer(input) ? input.toString("utf8") : input
  if (text.includes(FOCUS_IN)) {
    return {
      focused: true,
      supported: true,
    }
  }
  if (text.includes(FOCUS_OUT)) {
    return {
      focused: false,
      supported: true,
    }
  }
  return current
}
