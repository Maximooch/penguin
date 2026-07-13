import type {
  EventMessagePartUpdated,
  EventMessageRemoved,
  EventMessageUpdated,
  EventSessionStatus,
  TextPart,
  UserMessage,
} from "@opencode-ai/sdk/v2"

type Idle = EventSessionStatus
type Removed = EventMessageRemoved
type PenguinOptimisticEvent =
  | EventMessagePartUpdated
  | EventMessageUpdated
  | EventSessionStatus

export type PenguinOptimisticEmitter = (event: PenguinOptimisticEvent) => void

type PenguinPromptPart = {
  type: string
  mime?: string
  [key: string]: unknown
}

type PenguinModel = {
  providerID: string
  modelID: string
}

type PenguinAgentMode = "build" | "plan"

const SYNTHETIC_PENGUIN_PROVIDER_ID = "penguin"
const SYNTHETIC_PENGUIN_MODEL_ID = "penguin-default"
const SYNTHETIC_MODEL_MESSAGE =
  "Provider configuration is still loading. Try again once the model list finishes loading."

export function isPenguinSyntheticModel(model: PenguinModel | undefined): boolean {
  return model?.providerID === SYNTHETIC_PENGUIN_PROVIDER_ID && model.modelID === SYNTHETIC_PENGUIN_MODEL_ID
}

function assertPenguinSendableModel(model: PenguinModel) {
  if (!isPenguinSyntheticModel(model)) return
  throw new Error(SYNTHETIC_MODEL_MESSAGE)
}

export function recoverPenguinPromptFailure(input: {
  messageID?: string
  sessionID: string
  clear: () => void
  emit: (type: Idle["type"] | Removed["type"], event: Idle | Removed) => void
}) {
  input.clear()
  if (input.messageID) {
    const removed = {
      type: "message.removed",
      properties: {
        messageID: input.messageID,
        sessionID: input.sessionID,
      },
    } satisfies Removed
    input.emit(removed.type, removed)
  }
  const event = {
    type: "session.status",
    properties: {
      sessionID: input.sessionID,
      status: { type: "idle" },
    },
  } satisfies Idle
  input.emit(event.type, event)
}

export function completePenguinPromptSuccess(input: {
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

export function resolveSessionID(value: unknown): string | undefined {
  if (typeof value === "string" && value.trim()) return value.trim()
  if (!value || typeof value !== "object") return undefined
  const record = value as Record<string, unknown>
  if (typeof record.id === "string" && record.id.trim()) return record.id.trim()
  return resolveSessionID(record.data)
}

export async function createPenguinSession(input: {
  agentMode: PenguinAgentMode
  baseUrl: string | URL
  directory: string
  fetch: typeof fetch
  model: PenguinModel
  variant?: string
}): Promise<string> {
  assertPenguinSendableModel(input.model)
  const createUrl = new URL("/session", input.baseUrl)
  createUrl.searchParams.set("directory", input.directory)
  const created = await input
    .fetch(createUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        agent_mode: input.agentMode,
        providerID: input.model.providerID,
        modelID: input.model.modelID,
        variant: input.variant,
      }),
    })
    .then(async (res) => {
      if (!res.ok) {
        const details = await res.text().catch(() => "")
        throw new Error(
          details ? `Session create failed (${res.status}): ${details}` : `Session create failed (${res.status})`,
        )
      }
      return res.json().catch(() => undefined)
    })

  const sessionID = resolveSessionID(created)
  if (sessionID) return sessionID

  const details =
    created && typeof created === "object"
      ? `response keys: ${Object.keys(created as Record<string, unknown>).join(",") || "none"}`
      : `response type: ${typeof created}`
  throw new Error(`Session create returned empty id (${details})`)
}

export function shouldStripPenguinVirtualPart(part: { type: string; mime?: string }): boolean {
  return part.type === "file" && typeof part.mime === "string" && part.mime.startsWith("image/")
}

export function emitPenguinOptimisticPrompt(input: {
  agentName: string
  emit: PenguinOptimisticEmitter
  messageID: string
  model: PenguinModel
  now?: number
  partID: string
  sessionID: string
  text: string
}) {
  const now = input.now ?? Date.now()
  const user = {
    id: input.messageID,
    sessionID: input.sessionID,
    role: "user" as const,
    time: {
      created: now,
    },
    agent: input.agentName,
    model: {
      providerID: input.model.providerID,
      modelID: input.model.modelID,
    },
  } satisfies UserMessage
  const part = {
    id: input.partID,
    sessionID: input.sessionID,
    messageID: input.messageID,
    type: "text" as const,
    text: input.text,
    time: {
      start: now,
      end: now,
    },
  } satisfies TextPart

  const messageUpdated = {
    type: "message.updated",
    properties: { info: user },
  } satisfies EventMessageUpdated
  input.emit(messageUpdated)

  const messagePartUpdated = {
    type: "message.part.updated",
    properties: { part, delta: input.text },
  } satisfies EventMessagePartUpdated
  input.emit(messagePartUpdated)

  const sessionStatus = {
    type: "session.status",
    properties: {
      sessionID: input.sessionID,
      status: { type: "busy" as const },
    },
  } satisfies EventSessionStatus
  input.emit(sessionStatus)

  return { user, part }
}

export type PenguinPromptSendResult =
  | {
      ok: true
    }
  | {
      ok: false
      details?: string
      error?: unknown
      status?: number
    }

export async function sendPenguinPrompt(input: {
  agentMode: PenguinAgentMode
  agentName: string
  baseUrl: string | URL
  directory: string
  fetch: typeof fetch
  clientPartID?: string
  messageID: string
  model: PenguinModel
  parts: PenguinPromptPart[]
  serviceTier?: string
  sessionID: string
  text: string
  variant?: string
}): Promise<PenguinPromptSendResult> {
  if (isPenguinSyntheticModel(input.model)) {
    return {
      ok: false,
      details: SYNTHETIC_MODEL_MESSAGE,
    }
  }
  const url = new URL("/api/v1/chat/message", input.baseUrl)
  try {
    const res = await input.fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text: input.text,
        model: `${input.model.providerID}/${input.model.modelID}`,
        session_id: input.sessionID,
        agent_id: input.agentName,
        agent_mode: input.agentMode,
        directory: input.directory,
        streaming: true,
        variant: input.variant,
        service_tier: input.serviceTier,
        client_message_id: input.messageID,
        client_part_id: input.clientPartID,
        parts: input.parts,
      }),
    })
    if (res.ok) return { ok: true }
    return {
      ok: false,
      status: res.status,
      details: await res.text().catch(() => ""),
    }
  } catch (error) {
    return {
      ok: false,
      error,
    }
  }
}

export function formatPenguinPromptFailure(input: { status?: number; details?: string; error?: unknown }) {
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
