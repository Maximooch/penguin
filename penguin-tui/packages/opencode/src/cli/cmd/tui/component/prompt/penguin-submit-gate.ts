export type PenguinPromptSubmitRelease = () => void

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
