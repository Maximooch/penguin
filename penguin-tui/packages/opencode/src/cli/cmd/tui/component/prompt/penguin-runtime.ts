import type { PromptInfo } from "./history"

type PenguinFetch = (input: string | URL, init?: RequestInit) => Promise<Response>

export type PenguinPromptCommand = {
  name: string
  known: boolean
  keepDialog: boolean
}

export function resolvePenguinSessionID(value: unknown): string | undefined {
  if (typeof value === "string" && value.trim()) return value.trim()
  if (!value || typeof value !== "object") return undefined
  const record = value as Record<string, unknown>
  if (typeof record.id === "string" && record.id.trim()) return record.id.trim()
  return resolvePenguinSessionID(record.data)
}

export function parsePenguinPromptCommand(inputText: string): PenguinPromptCommand | undefined {
  const firstLine = inputText.split("\n", 1)[0].trim()
  const firstToken = firstLine.split(/\s+/, 1)[0] ?? ""
  const penguinCommand = /^\/[a-z_][a-z0-9_-]*$/i.test(firstToken)
  if (!penguinCommand) return undefined
  const name = firstToken.slice(1)
  const known = name === "config" || name === "settings" || name === "tool_details" || name === "thinking"
  return {
    name,
    known,
    keepDialog: name === "config" || name === "settings",
  }
}

export function createOptimisticPenguinEvents(input: {
  sessionID: string
  messageID: string
  partID: string
  inputText: string
  agentName: string
  providerID: string
  modelID: string
  now?: number
}) {
  const now = input.now ?? Date.now()
  return {
    message: {
      type: "message.updated" as const,
      properties: {
        info: {
          id: input.messageID,
          sessionID: input.sessionID,
          role: "user" as const,
          time: {
            created: now,
          },
          agent: input.agentName,
          model: {
            providerID: input.providerID,
            modelID: input.modelID,
          },
        },
      },
    },
    part: {
      type: "message.part.updated" as const,
      properties: {
        part: {
          id: input.partID,
          sessionID: input.sessionID,
          messageID: input.messageID,
          type: "text" as const,
          text: input.inputText,
          time: {
            start: now,
            end: now,
          },
        },
        delta: input.inputText,
      },
    },
    status: {
      type: "session.status" as const,
      properties: {
        sessionID: input.sessionID,
        status: {
          type: "busy" as const,
        },
      },
    },
  }
}

export function persistPenguinAgentMode(input: {
  fetch: PenguinFetch
  url: string
  sessionID: string
  mode: "build" | "plan"
}): Promise<Response | undefined> {
  const modeUrl = new URL(`/session/${encodeURIComponent(input.sessionID)}`, input.url)
  return input
    .fetch(modeUrl, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ agent_mode: input.mode }),
    })
    .catch(() => undefined)
}

export async function createPenguinSession(input: {
  fetch: PenguinFetch
  url: string
  directory: string
  agentMode: "build" | "plan"
  providerID: string
  modelID: string
  variant?: string
}): Promise<string> {
  const createUrl = new URL("/session", input.url)
  createUrl.searchParams.set("directory", input.directory)
  const created = await input
    .fetch(createUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        agent_mode: input.agentMode,
        providerID: input.providerID,
        modelID: input.modelID,
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

  const createdID = resolvePenguinSessionID(created)
  if (createdID) return createdID
  const details =
    created && typeof created === "object"
      ? `response keys: ${Object.keys(created as Record<string, unknown>).join(",") || "none"}`
      : `response type: ${typeof created}`
  throw new Error(`Session create returned empty id (${details})`)
}

export function postPenguinPrompt(input: {
  fetch: PenguinFetch
  url: string
  text: string
  providerID: string
  modelID: string
  sessionID: string
  agentName: string
  agentMode: "build" | "plan"
  directory: string
  variant?: string
  clientMessageID: string
  parts: PromptInfo["parts"]
}) {
  const target = new URL("/api/v1/chat/message", input.url)
  return input.fetch(target, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      text: input.text,
      model: `${input.providerID}/${input.modelID}`,
      session_id: input.sessionID,
      agent_id: input.agentName,
      agent_mode: input.agentMode,
      directory: input.directory,
      streaming: true,
      variant: input.variant,
      client_message_id: input.clientMessageID,
      parts: input.parts,
    }),
  })
}
