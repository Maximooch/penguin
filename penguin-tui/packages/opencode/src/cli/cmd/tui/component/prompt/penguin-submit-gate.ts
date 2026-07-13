export type PenguinPromptSubmitRelease = () => void

export type PenguinPromptSubmitGate = {
  readonly active: boolean
  tryStart(options?: PenguinPromptSubmitTimeout): PenguinPromptSubmitRelease | undefined
}

export type PenguinPromptSubmitTimeout = {
  onTimeout?: () => void
  timeoutMs?: number
}

type PenguinPromptSubmitSchedule = (callback: () => void, timeoutMs: number) => () => void

export type PenguinPromptSubmitStart =
  | {
      ok: true
      release: PenguinPromptSubmitRelease
    }
  | {
      ok: false
      reason: "busy" | "submitting"
    }

export function createPenguinPromptSubmitGate(options?: { schedule?: PenguinPromptSubmitSchedule }) {
  const state = {
    active: 0,
    next: 1,
  }
  const schedule: PenguinPromptSubmitSchedule =
    options?.schedule ??
    ((callback, timeoutMs) => {
      const timer = setTimeout(callback, timeoutMs)
      return () => clearTimeout(timer)
    })

  return {
    get active() {
      return state.active !== 0
    },
    tryStart(timeout?: PenguinPromptSubmitTimeout): PenguinPromptSubmitRelease | undefined {
      if (state.active) return undefined
      const token = state.next++
      state.active = token
      const cancel =
        timeout?.timeoutMs === undefined
          ? undefined
          : schedule(
              () => {
                if (state.active !== token) return
                state.active = 0
                timeout.onTimeout?.()
              },
              Math.max(0, timeout.timeoutMs),
            )
      return () => {
        cancel?.()
        if (state.active === token) state.active = 0
      }
    },
  }
}

export function tryStartPenguinPromptSubmit(input: {
  busy: boolean
  gate: PenguinPromptSubmitGate
  allowWhileBusy?: boolean
  onTimeout?: () => void
  timeoutMs?: number
}): PenguinPromptSubmitStart {
  if (input.busy && !input.allowWhileBusy) {
    return {
      ok: false,
      reason: "busy",
    }
  }

  const release = input.gate.tryStart({
    onTimeout: input.onTimeout,
    timeoutMs: input.timeoutMs,
  })
  if (!release) {
    return {
      ok: false,
      reason: "submitting",
    }
  }

  return {
    ok: true,
    release,
  }
}
