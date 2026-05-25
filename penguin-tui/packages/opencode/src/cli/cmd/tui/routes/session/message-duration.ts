type MessageTime = {
  completed?: number
  created?: number
}

export type DurationMessage = {
  finish?: string
  id: string
  parentID?: string
  role: string
  time?: MessageTime
}

function validTime(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value)
}

export function isAssistantSettled(message: DurationMessage): boolean {
  if (message.role !== "assistant") return false
  if (validTime(message.time?.completed)) return true
  return !!message.finish && !["tool-calls", "unknown"].includes(message.finish)
}

function userStartedAt(message: DurationMessage | undefined): number | undefined {
  if (!message || message.role !== "user") return undefined
  const created = message.time?.created
  return validTime(created) ? created : undefined
}

export function assistantDurationMs(message: DurationMessage, messages: DurationMessage[]): number {
  if (message.role !== "assistant") return 0

  const completed = message.time?.completed
  if (!validTime(completed)) return 0

  const parentID = message.parentID && message.parentID !== "root" ? message.parentID : undefined
  const parentStartedAt = userStartedAt(parentID ? messages.find((item) => item.id === parentID) : undefined)
  if (parentStartedAt !== undefined) return Math.max(0, completed - parentStartedAt)

  const messageIndex = messages.findIndex((item) => item.id === message.id)
  const previousMessages = messageIndex === -1 ? messages : messages.slice(0, messageIndex)
  for (let i = previousMessages.length - 1; i >= 0; i--) {
    const startedAt = userStartedAt(previousMessages[i])
    if (startedAt !== undefined) return Math.max(0, completed - startedAt)
  }

  return 0
}
