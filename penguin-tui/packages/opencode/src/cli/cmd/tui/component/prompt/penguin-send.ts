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
}

export function completePenguinPromptSuccess(input: {
  sessionID: string
  clear: () => void
  emit: (type: Idle["type"], event: Idle) => void
}) {
  input.clear()
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
  signal?: AbortSignal
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
      signal: input.signal,
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
      terminal: PenguinPromptTerminal
    }
  | {
      aborted?: boolean
      ok: false
      details?: string
      error?: unknown
      status?: number
      timedOut?: boolean
    }

export const DEFAULT_PENGUIN_PROMPT_TIMEOUT_MS = 35 * 60 * 1000

export type PenguinPromptTerminal = {
  aborted: boolean
  actionCount: number
  actionResults: unknown[]
  actions: unknown[]
  cancelled: boolean
  completed: boolean
  continuation?: Record<string, unknown>
  error?: unknown
  iterations?: number
  legacy: boolean
  partialResponse: string
  recoverable: boolean
  response: string
  runtimeDiagnostics?: Record<string, unknown>
  state: string
  status: string
  terminalReason?: string
}

export type PenguinPromptContinuation = {
  action: string
  endpoint: string
  label: string
  method: "POST"
  request: Record<string, unknown>
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined
  return value as Record<string, unknown>
}

function asText(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function asOptionalText(value: unknown): string | undefined {
  const text = asText(value).trim()
  return text || undefined
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined
}

export function parsePenguinPromptTerminal(value: unknown): PenguinPromptTerminal {
  const data = asRecord(value) ?? {}
  const truth = [
    "status",
    "state",
    "terminal_reason",
    "completed",
    "recoverable",
    "aborted",
    "cancelled",
    "continuation",
    "actions",
  ].some((key) => key in data)
  const legacy = !truth
  const rawStatus = asOptionalText(data.status)
  const cancelled = asBoolean(data.cancelled) ?? rawStatus === "cancelled"
  const aborted = asBoolean(data.aborted) ?? rawStatus === "aborted"
  const explicitCompleted = asBoolean(data.completed)
  const completed =
    explicitCompleted ?? (legacy || rawStatus === "completed" || rawStatus === "success" || rawStatus === "succeeded")
  const status = rawStatus ?? (completed ? "completed" : cancelled ? "cancelled" : aborted ? "aborted" : "incomplete")
  const state =
    asOptionalText(data.state) ?? (completed ? "completed" : cancelled ? "cancelled" : aborted ? "aborted" : "failed")
  const actionResults = Array.isArray(data.action_results) ? data.action_results : []
  const actions = Array.isArray(data.actions) ? data.actions : []
  const continuation = asRecord(data.continuation)
  const runtimeDiagnostics = asRecord(data.runtime_diagnostics)
  const response = asText(data.response)
  const partialResponse = asText(data.partial_response) || (completed ? "" : response)

  return {
    aborted,
    actionCount: asNumber(data.action_count) ?? actionResults.length,
    actionResults,
    actions,
    cancelled,
    completed,
    continuation,
    error: data.error,
    iterations: asNumber(data.iterations),
    legacy,
    partialResponse,
    recoverable: asBoolean(data.recoverable) ?? continuation?.available === true,
    response,
    runtimeDiagnostics,
    state,
    status,
    terminalReason: asOptionalText(data.terminal_reason),
  }
}

function humanizePenguinTerminalValue(value: string): string {
  return value.replaceAll("_", " ").replaceAll("-", " ").replace(/\s+/g, " ").trim()
}

export function getPenguinPromptTerminalActionLabels(terminal: PenguinPromptTerminal): string[] {
  const entries = terminal.actions.flatMap((value) => {
    if (typeof value === "string" && value.trim()) return [{ key: value.trim(), label: value.trim() }]
    const action = asRecord(value)
    const label = asOptionalText(action?.label) ?? asOptionalText(action?.action)
    const key = asOptionalText(action?.action) ?? label
    return label && key ? [{ key, label }] : []
  })
  const continuation = terminal.continuation
  const continuationAction = continuation?.available === true ? asOptionalText(continuation.action) : undefined
  const seen = new Set(entries.flatMap((entry) => [entry.key.toLowerCase(), entry.label.toLowerCase()]))
  const labels = [...new Set(entries.map((entry) => entry.label))]
  if (!continuationAction || seen.has(continuationAction.toLowerCase())) return labels
  return [...labels, continuationAction]
}

export function formatPenguinPromptTerminal(terminal: PenguinPromptTerminal): string {
  const reason = humanizePenguinTerminalValue(terminal.terminalReason ?? terminal.status)
  const prefix = terminal.cancelled || terminal.aborted ? "Penguin cancelled" : "Penguin stopped"
  const labels = getPenguinPromptTerminalActionLabels(terminal)
  if (labels.length === 0) return `${prefix}: ${reason}`
  return `${prefix}: ${reason} · available: ${labels.join(", ")}`
}

function compactPenguinTerminalText(value: string, limit = 160): string {
  const compact = value.replace(/\s+/g, " ").trim()
  if (compact.length <= limit) return compact
  return `${compact.slice(0, Math.max(0, limit - 1))}…`
}

function penguinTerminalErrorSummary(error: unknown): string | undefined {
  if (typeof error === "string" && error.trim()) return compactPenguinTerminalText(error)
  const record = asRecord(error)
  const code = asOptionalText(record?.code)
  const message = asOptionalText(record?.message)
  if (code && message) return `${humanizePenguinTerminalValue(code)}: ${compactPenguinTerminalText(message)}`
  return message ? compactPenguinTerminalText(message) : code ? humanizePenguinTerminalValue(code) : undefined
}

export function isPenguinTerminalInterruptible(terminal: PenguinPromptTerminal | undefined): boolean {
  if (!terminal || terminal.completed) return false
  return terminal.status === "client_timeout" || terminal.status === "request_gate_timeout" || terminal.state === "stalled"
}

export function formatPenguinPromptTerminalDetails(terminal: PenguinPromptTerminal): string {
  const lines = [formatPenguinPromptTerminal(terminal)]
  const partial = compactPenguinTerminalText(terminal.partialResponse)
  if (partial) lines.push(`partial: ${partial}`)
  if (terminal.actionCount > 0) lines.push(`tool results: ${terminal.actionCount}`)
  const error = penguinTerminalErrorSummary(terminal.error)
  if (error) lines.push(`detail: ${error}`)
  if (isPenguinTerminalInterruptible(terminal)) lines.push("Esc interrupt")
  return lines.join("\n")
}

export function getPenguinPromptContinuation(
  terminal: PenguinPromptTerminal | undefined,
): PenguinPromptContinuation | undefined {
  const continuation = terminal?.continuation
  if (!continuation || continuation.available !== true) return undefined
  const method = asOptionalText(continuation.method)?.toUpperCase()
  const endpoint = asOptionalText(continuation.endpoint)
  const request = asRecord(continuation.request)
  const action = asOptionalText(continuation.action)
  if (method !== "POST" || !endpoint || !request || !action) return undefined
  const label = asOptionalText(continuation.label) ?? action
  return {
    action,
    endpoint,
    label,
    method,
    request,
  }
}

function createPenguinPromptDeadline(input: { signal?: AbortSignal; timeoutMs?: number }) {
  const controller = new AbortController()
  const state = { timedOut: false }
  const relay = () => controller.abort(input.signal?.reason)
  if (input.signal?.aborted) relay()
  if (!input.signal?.aborted) input.signal?.addEventListener("abort", relay, { once: true })
  const timeoutMs = input.timeoutMs ?? DEFAULT_PENGUIN_PROMPT_TIMEOUT_MS
  const timer = setTimeout(
    () => {
      state.timedOut = true
      controller.abort(new DOMException(`Penguin prompt timed out after ${timeoutMs}ms`, "TimeoutError"))
    },
    Math.max(0, timeoutMs),
  )

  return {
    clear() {
      clearTimeout(timer)
      input.signal?.removeEventListener("abort", relay)
    },
    controller,
    state,
  }
}

export async function abortPenguinSession(input: {
  baseUrl: string | URL
  directory?: string
  fetch: typeof fetch
  sessionID: string
  timeoutMs?: number
}): Promise<boolean> {
  const url = new URL(`/session/${encodeURIComponent(input.sessionID)}/abort`, input.baseUrl)
  if (input.directory) url.searchParams.set("directory", input.directory)
  const deadline = createPenguinPromptDeadline({ timeoutMs: input.timeoutMs ?? 5_000 })
  try {
    const res = await input.fetch(url, {
      method: "POST",
      signal: deadline.controller.signal,
    })
    return res.ok
  } catch {
    return false
  } finally {
    deadline.clear()
  }
}

async function parsePenguinPromptResponse(res: Response): Promise<PenguinPromptSendResult> {
  if (!res.ok) {
    return {
      ok: false,
      status: res.status,
      details: await res.text().catch(() => ""),
    }
  }

  const details = await res.text().catch((error) => error)
  if (typeof details !== "string") {
    return {
      ok: false,
      status: res.status,
      error: details,
      details: "Failed to read the Penguin terminal response.",
    }
  }
  if (!details.trim()) {
    return { ok: false, status: res.status, details: "Penguin returned an empty 2xx terminal response." }
  }
  try {
    const parsed = JSON.parse(details)
    const data = asRecord(parsed)
    if (!data) throw new Error("expected a JSON object")
    validatePenguinPromptTerminalResponse(data)
    return {
      ok: true,
      terminal: parsePenguinPromptTerminal(data),
    }
  } catch (error) {
    return {
      ok: false,
      status: res.status,
      details: `Invalid Penguin terminal response: ${error instanceof Error ? error.message : String(error)}`,
    }
  }
}

const COMPLETED_TERMINAL_STATUSES = new Set(["completed", "implicit_completion", "pending_review", "success"])
const MAX_ITERATION_TERMINAL_STATUSES = new Set(["max_iterations", "iterations_exceeded"])
const PROVIDER_EXHAUSTED_TERMINAL_STATUSES = new Set([
  "provider_recoverable_error",
  "provider_timeout",
  "provider_disconnect",
  "request_timeout",
])
const STALLED_TERMINAL_STATUSES = new Set([
  "llm_empty_response_error",
  "repeated_empty_tool_only_iterations",
  "repeated_empty_response",
  "repeated_response",
  "request_gate_timeout",
  "tool_result_echo",
  "stalled",
])

function expectedPenguinTerminalState(status: string, input: { aborted: boolean; cancelled: boolean }): string {
  if (input.cancelled) return "cancelled"
  if (input.aborted) return "aborted"
  if (COMPLETED_TERMINAL_STATUSES.has(status)) return "completed"
  if (status === "stopped") return "stopped"
  if (MAX_ITERATION_TERMINAL_STATUSES.has(status)) return "max_iterations"
  if (PROVIDER_EXHAUSTED_TERMINAL_STATUSES.has(status)) return "provider_exhausted"
  if (STALLED_TERMINAL_STATUSES.has(status)) return "stalled"
  if (status === "cancelled") return "cancelled"
  if (status === "aborted") return "aborted"
  return "failed"
}

function validatePenguinPromptTerminalResponse(data: Record<string, unknown>) {
  for (const key of ["status", "state", "completed", "recoverable"] as const) {
    if (!(key in data)) throw new Error(`missing required terminal field ${key}`)
  }
  const status = asOptionalText(data.status)
  const state = asOptionalText(data.state)
  const completed = asBoolean(data.completed)
  const recoverable = asBoolean(data.recoverable)
  if (!status || !state || completed === undefined || recoverable === undefined) {
    throw new Error("terminal truth fields have invalid types")
  }
  const aborted = asBoolean(data.aborted) ?? false
  const cancelled = asBoolean(data.cancelled) ?? false
  if (aborted && cancelled) throw new Error("terminal cannot be both aborted and cancelled")
  if (status === "aborted" && !aborted) throw new Error("aborted status contradicts aborted=false")
  if (status === "cancelled" && !cancelled) throw new Error("cancelled status contradicts cancelled=false")
  const expectedState = expectedPenguinTerminalState(status, { aborted, cancelled })
  if (state !== expectedState) throw new Error(`terminal state ${state} contradicts status ${status}`)
  if (completed && state !== "completed") throw new Error("completed=true contradicts terminal state")
  if (!completed && state === "completed") throw new Error("completed=false contradicts terminal state")
  if (completed && recoverable) throw new Error("completed terminal cannot be recoverable")
  if (completed && (aborted || cancelled)) throw new Error("completed terminal cannot be aborted or cancelled")
  if (completed && data.error !== undefined && data.error !== null) {
    throw new Error("completed terminal cannot contain an error")
  }
  const continuation = asRecord(data.continuation)
  if (completed && continuation?.available === true) {
    throw new Error("completed terminal cannot advertise continuation")
  }
  if (!recoverable && continuation?.available === true) {
    throw new Error("non-recoverable terminal cannot advertise continuation")
  }
  const actionResults = Array.isArray(data.action_results) ? data.action_results : undefined
  const actionCount = asNumber(data.action_count)
  if (actionResults && actionCount !== undefined && actionCount !== actionResults.length) {
    throw new Error("action_count contradicts action_results")
  }
  if (!completed && status === "completed") throw new Error("completed status contradicts completed=false")
}

export async function fetchPenguinTerminalState(input: {
  baseUrl: string | URL
  directory?: string
  fetch: typeof fetch
  sessionID: string
  signal?: AbortSignal
}): Promise<PenguinPromptTerminal | undefined> {
  const url = new URL(`/api/v1/session/${encodeURIComponent(input.sessionID)}/terminal`, input.baseUrl)
  if (input.directory) url.searchParams.set("directory", input.directory)
  const res = await input.fetch(url, { signal: input.signal })
  if (res.status === 404) return undefined
  const result = await parsePenguinPromptResponse(res)
  if (result.ok) return result.terminal
  throw new Error(result.details || `Terminal hydration failed (${result.status ?? "transport"})`)
}

export async function sendPenguinContinuation(input: {
  baseUrl: string | URL
  fetch: typeof fetch
  signal?: AbortSignal
  terminal: PenguinPromptTerminal
  timeoutMs?: number
}): Promise<PenguinPromptSendResult> {
  const continuation = getPenguinPromptContinuation(input.terminal)
  if (!continuation) {
    return {
      ok: false,
      details: "The terminal response did not provide a valid continuation request.",
    }
  }

  const base = new URL(input.baseUrl)
  const url = new URL(continuation.endpoint, base)
  if (url.origin !== base.origin) {
    return {
      ok: false,
      details: "Refusing a cross-origin Penguin continuation request.",
    }
  }

  const deadline = createPenguinPromptDeadline({
    signal: input.signal,
    timeoutMs: input.timeoutMs,
  })
  try {
    const res = await input.fetch(url, {
      method: continuation.method,
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(continuation.request),
      signal: deadline.controller.signal,
    })
    return await parsePenguinPromptResponse(res)
  } catch (error) {
    return {
      aborted: deadline.controller.signal.aborted && !deadline.state.timedOut,
      ok: false,
      error,
      timedOut: deadline.state.timedOut,
    }
  } finally {
    deadline.clear()
  }
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
  signal?: AbortSignal
  text: string
  timeoutMs?: number
  variant?: string
}): Promise<PenguinPromptSendResult> {
  if (isPenguinSyntheticModel(input.model)) {
    return {
      ok: false,
      details: SYNTHETIC_MODEL_MESSAGE,
    }
  }
  const url = new URL("/api/v1/chat/message", input.baseUrl)
  const deadline = createPenguinPromptDeadline({
    signal: input.signal,
    timeoutMs: input.timeoutMs,
  })
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
      signal: deadline.controller.signal,
    })
    return await parsePenguinPromptResponse(res)
  } catch (error) {
    return {
      aborted: deadline.controller.signal.aborted && !deadline.state.timedOut,
      ok: false,
      error,
      timedOut: deadline.state.timedOut,
    }
  } finally {
    deadline.clear()
  }
}

export function formatPenguinPromptFailure(input: {
  aborted?: boolean
  status?: number
  details?: string
  error?: unknown
  timedOut?: boolean
}) {
  if (input.timedOut) {
    return "Failed to send message: the Penguin request timed out. The session may still be recoverable; check status before retrying."
  }
  if (input.aborted) return "Penguin request cancelled."
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
