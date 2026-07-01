export type ReasoningSummary = {
  title: string | null
  body: string
}

type ReasoningCompletionInput = {
  part: {
    time?: {
      end?: number
    } | null
  }
  message: {
    time?: {
      completed?: number
    } | null
  }
}

export function parseReasoningSummary(text: string): ReasoningSummary {
  const content = text.trim()
  const match = content.match(/^\*\*([^*\n]+)\*\*(?:\r?\n\r?\n|$)/)
  if (!match) return { title: null, body: content }

  return {
    title: match[1]?.trim() || null,
    body: content.slice(match[0].length).trimEnd(),
  }
}

export function formatReasoningHeader(title: string | null): string {
  return title ? `_Thinking: ${title}_` : "_Thinking:_"
}

export function formatReasoningLabel(title: string | null, done: boolean): string {
  const prefix = done ? "Thought" : "Thinking"
  return title ? `${prefix}: ${title}` : prefix
}

export function isReasoningComplete(input: ReasoningCompletionInput): boolean {
  return input.part.time?.end !== undefined || input.message.time?.completed !== undefined
}
