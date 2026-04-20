type Idle = {
  type: "session.status"
  properties: {
    sessionID: string
    status: {
      type: "idle"
    }
  }
}

export function recoverPenguinPromptFailure(input: {
  sessionID: string
  clear: () => void
  emit: (type: Idle["type"], event: Idle) => void
}) {
  input.clear()
  const event = {
    type: "session.status",
    properties: {
      sessionID: input.sessionID,
      status: { type: "idle" },
    },
  } satisfies Idle
  input.emit(event.type, event)
}

export function formatPenguinPromptFailure(input: {
  status?: number
  details?: string
  error?: unknown
}) {
  const details = input.details?.trim()
  if (details) return `Failed to send message: ${details}`

  const error =
    input.error instanceof Error
      ? input.error.message.trim()
      : typeof input.error === "string"
        ? input.error.trim()
        : ""
  if (error) {
    return `Failed to send message: ${error}. Check local auth/server connectivity and try again.`
  }

  if (input.status === 401 || input.status === 403) {
    return `Failed to send message (${input.status}). Check local auth and try again.`
  }

  if (typeof input.status === "number") {
    return `Failed to send message (${input.status}). Check local auth/server connectivity and try again.`
  }

  return "Failed to send message. Check local auth/server connectivity and try again."
}
