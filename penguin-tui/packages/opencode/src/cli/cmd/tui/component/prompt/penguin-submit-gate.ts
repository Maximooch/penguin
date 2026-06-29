export type PenguinPromptSubmitRelease = () => void

export type PenguinPromptSubmitGate = {
  readonly active: boolean
  tryStart(): PenguinPromptSubmitRelease | undefined
}

export type PenguinPromptSubmitStart =
  | {
      ok: true
      release: PenguinPromptSubmitRelease
    }
  | {
      ok: false
      reason: "busy" | "submitting"
    }

export function createPenguinPromptSubmitGate() {
  const state = {
    active: 0,
    next: 1,
  }

  return {
    get active() {
      return state.active !== 0
    },
    tryStart(): PenguinPromptSubmitRelease | undefined {
      if (state.active) return undefined
      const token = state.next++
      state.active = token
      return () => {
        if (state.active === token) state.active = 0
      }
    },
  }
}

export function tryStartPenguinPromptSubmit(input: {
  busy: boolean
  gate: PenguinPromptSubmitGate
}): PenguinPromptSubmitStart {
  if (input.busy) {
    return {
      ok: false,
      reason: "busy",
    }
  }

  const release = input.gate.tryStart()
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
