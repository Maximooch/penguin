const DEFAULT_DUPLICATE_PASTE_WINDOW_MS = 100

export function normalizePastedText(text: string) {
  return text.replace(/\r\n/g, "\n").replace(/\r/g, "\n")
}

export function shouldSummarizePaste(text: string, disablePasteSummary?: boolean) {
  if (disablePasteSummary) return false

  const lineCount = (text.match(/\n/g)?.length ?? 0) + 1
  return lineCount >= 3 || text.length > 150
}

export function shouldOwnPasteEvent(text: string) {
  return normalizePastedText(text).length > 0
}

export function createPasteDuplicateGuard(options?: { now?: () => number; windowMs?: number }) {
  const now = options?.now ?? Date.now
  const windowMs = options?.windowMs ?? DEFAULT_DUPLICATE_PASTE_WINDOW_MS
  let lastText = ""
  let lastAt = Number.NEGATIVE_INFINITY

  return {
    shouldDrop(text: string) {
      if (!text) return false

      const current = now()
      const duplicate = text === lastText && current - lastAt <= windowMs
      lastText = text
      lastAt = current
      return duplicate
    },
  }
}
