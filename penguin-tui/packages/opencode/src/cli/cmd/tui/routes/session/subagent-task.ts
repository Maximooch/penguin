import { Locale } from "@/util/locale"

export function formatSubagentTaskLabel(input: { background?: boolean; subagentType?: string }): string {
  const agent = Locale.titlecase(input.subagentType ?? "unknown")
  return `${agent} Task${input.background ? " (background)" : ""}`
}

export function isBackgroundSubagentTask(metadata: unknown): boolean {
  if (typeof metadata !== "object" || metadata === null) return false
  return "background" in metadata && metadata.background === true
}

export function formatSubagentToolcalls(count: number): string {
  return `${count} toolcall${count === 1 ? "" : "s"}`
}

export function formatSubagentTaskDescription(input: { description?: string; toolcalls?: number }): string {
  const description = input.description ?? ""
  if (input.toolcalls === undefined) return description
  return `${description} (${formatSubagentToolcalls(input.toolcalls)})`
}
