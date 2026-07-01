import type { AgentPart, FilePart, TextPart } from "@opencode-ai/sdk/v2"
import { clone } from "remeda"
import z from "zod"

export type PromptInfo = {
  input: string
  mode?: "normal" | "shell"
  parts: (
    | Omit<FilePart, "id" | "messageID" | "sessionID">
    | Omit<AgentPart, "id" | "messageID" | "sessionID">
    | (Omit<TextPart, "id" | "messageID" | "sessionID"> & {
        source?: {
          text: {
            start: number
            end: number
            value: string
          }
        }
      })
  )[]
}

const MAX_HISTORY_ENTRIES = 50

export function emptyPrompt(): PromptInfo {
  return {
    input: "",
    parts: [],
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function hasSourceText(value: unknown): boolean {
  if (!isRecord(value)) return false
  return typeof value.start === "number" && typeof value.end === "number" && typeof value.value === "string"
}

function hasTextSource(value: unknown): boolean {
  if (value === undefined) return true
  if (!isRecord(value)) return false
  return hasSourceText(value.text)
}

function hasAgentSource(value: unknown): boolean {
  if (value === undefined) return true
  return hasSourceText(value)
}

const promptPartSchema = z.custom<PromptInfo["parts"][number]>((value) => {
  if (!isRecord(value)) return false
  switch (value.type) {
    case "text":
      return typeof value.text === "string" && hasTextSource(value.source)
    case "file":
      return typeof value.mime === "string" && typeof value.url === "string" && hasTextSource(value.source)
    case "agent":
      return typeof value.name === "string" && hasAgentSource(value.source)
    default:
      return false
  }
})

const promptHistoryRowSchema: z.ZodType<PromptInfo> = z
  .object({
    input: z.string(),
    mode: z.enum(["normal", "shell"]).optional(),
    parts: z.array(promptPartSchema),
  })
  .passthrough()

export function parsePromptHistoryLine(line: string): PromptInfo | null {
  try {
    const parsed = JSON.parse(line)
    const result = promptHistoryRowSchema.safeParse(parsed)
    return result.success ? result.data : null
  } catch {
    return null
  }
}

function promptCopy(prompt: PromptInfo): PromptInfo {
  return clone(prompt)
}

export function samePrompt(a: PromptInfo, b: PromptInfo): boolean {
  return a.mode === b.mode && a.input === b.input && JSON.stringify(a.parts) === JSON.stringify(b.parts)
}

export function normalizePromptHistory(items: PromptInfo[]): PromptInfo[] {
  const next: PromptInfo[] = []
  for (const item of items) {
    if (!item.input.trim()) continue
    const entry = promptCopy(item)
    if (next.length > 0 && samePrompt(next[next.length - 1], entry)) continue
    next.push(entry)
  }
  return next.slice(-MAX_HISTORY_ENTRIES)
}

export function appendPromptHistory(items: PromptInfo[], item: PromptInfo): PromptInfo[] {
  if (!item.input.trim()) return items
  const entry = promptCopy(item)
  const last = items[items.length - 1]
  if (last && samePrompt(last, entry)) return items
  return [...items, entry].slice(-MAX_HISTORY_ENTRIES)
}

export type PromptHistoryBrowseState = {
  draft: PromptInfo
  history: PromptInfo[]
  index: number | null
}

export function movePromptHistory(
  state: PromptHistoryBrowseState,
  direction: 1 | -1,
  prompt: PromptInfo,
): {
  state: PromptHistoryBrowseState
  prompt?: PromptInfo
} {
  if (!state.history.length) return { state }
  if (state.index === null) {
    if (direction === 1) return { state }
    const index = state.history.length - 1
    return {
      state: {
        ...state,
        draft: promptCopy(prompt),
        index,
      },
      prompt: promptCopy(state.history[index]),
    }
  }

  const index = state.index + direction
  if (index < 0) return { state }
  if (index >= state.history.length) {
    return {
      state: {
        ...state,
        draft: emptyPrompt(),
        index: null,
      },
      prompt: promptCopy(state.draft),
    }
  }

  return {
    state: {
      ...state,
      index,
    },
    prompt: promptCopy(state.history[index]),
  }
}
