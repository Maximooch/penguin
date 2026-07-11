const DEFAULT_DUPLICATE_PASTE_WINDOW_MS = 100

export type PromptVirtualPart = {
  type: string
  text?: string
  mime?: string
}

export type PromptVirtualExtmark = {
  id: number
  start: number
  end: number
}

export type PasteTaskQueue = {
  enqueue(task: () => void | Promise<void>): Promise<void>
  drain(): Promise<void>
}

export function normalizePastedText(text: string) {
  return text.replace(/\r\n/g, "\n").replace(/\r/g, "\n")
}

/** Materialize virtual prompt parts into the text that will be submitted. */
export function materializePromptText(input: {
  text: string
  parts: readonly PromptVirtualPart[]
  extmarks: readonly PromptVirtualExtmark[]
  extmarkToPartIndex: ReadonlyMap<number, number>
  shouldStripVirtualPart?: (part: PromptVirtualPart) => boolean
}): string {
  let text = input.text
  const extmarks = [...input.extmarks].sort((a, b) => b.start - a.start)

  for (const extmark of extmarks) {
    const partIndex = input.extmarkToPartIndex.get(extmark.id)
    if (partIndex === undefined) continue
    const part = input.parts[partIndex]
    if (!part) continue

    const before = text.slice(0, extmark.start)
    const after = text.slice(extmark.end)
    if (part.type === "text" && part.text) {
      text = before + part.text + after
      continue
    }
    if (input.shouldStripVirtualPart?.(part)) {
      text = before + after
    }
  }

  return text
}

/** Serialize asynchronous paste work so a submit can await the final input. */
export function createPasteTaskQueue(): PasteTaskQueue {
  let tail: Promise<void> = Promise.resolve()

  return {
    enqueue(task) {
      const result = tail.then(task)
      tail = result.then(
        () => undefined,
        () => undefined,
      )
      return result
    },
    drain() {
      return tail
    },
  }
}

export function shouldSummarizePaste(text: string, disablePasteSummary?: boolean) {
  if (disablePasteSummary) return false

  const normalizedText = normalizePastedText(text)
  const lineCount = (normalizedText.match(/\n/g)?.length ?? 0) + 1
  return lineCount >= 3 || normalizedText.length > 150
}

export function shouldOwnPasteEvent(text: string) {
  return normalizePastedText(text).length > 0
}

export function removePastedPathReferences(text: string, references: string[]) {
  const variants = references
    .filter((item, index, all) => !!item && all.indexOf(item) === index)
    .flatMap((item) => [item, item.replace(/\\ /g, " "), item.replace(/ /g, "\\ ")])
    .filter((item, index, all) => !!item && all.indexOf(item) === index)

  return variants
    .reduce((next, item) => next.split(item).join(" "), text)
    .replace(/\s+/g, " ")
    .trim()
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
