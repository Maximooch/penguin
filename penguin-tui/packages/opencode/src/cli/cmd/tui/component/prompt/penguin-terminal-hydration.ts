import { createRenderEffect, onCleanup } from "solid-js"
import { fetchPenguinTerminalState, type PenguinPromptTerminal } from "./penguin-send"

export function mountPenguinTerminalHydration(input: {
  active: () => boolean
  baseUrl: string | URL
  directory: (sessionID: string) => string | undefined
  epoch?: () => unknown
  fetch: typeof fetch
  locallyActive: () => boolean
  onTerminal: (terminal: PenguinPromptTerminal | undefined) => void
  sessionID: () => string
}) {
  createRenderEffect(() => {
    const epoch = input.epoch?.()
    const sessionID = input.sessionID()
    if (!input.active() || !sessionID || input.locallyActive()) return
    const controller = new AbortController()
    onCleanup(() => controller.abort())
    void fetchPenguinTerminalState({
      baseUrl: input.baseUrl,
      directory: input.directory(sessionID),
      fetch: input.fetch,
      sessionID,
      signal: controller.signal,
    })
      .then((terminal) => {
        if (
          controller.signal.aborted ||
          input.sessionID() !== sessionID ||
          input.locallyActive() ||
          input.epoch?.() !== epoch
        ) {
          return
        }
        input.onTerminal(terminal && !terminal.completed ? terminal : undefined)
      })
      .catch(() => undefined)
  })
}
