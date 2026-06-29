import type {
  Agent,
  Command,
  Config,
  Provider,
  ProviderAuthMethod,
  ProviderListResponse,
  Session,
  SessionStatus,
} from "@opencode-ai/sdk/v2"
import type { Path } from "@opencode-ai/sdk"
import { Log } from "@/util/log"
import z from "zod"

type BootstrapFetch = (input: string | URL, init?: RequestInit) => Promise<Response>

export type SessionUsage = {
  current_total_tokens: number
  max_context_window_tokens: number | null
  available_tokens: number
  percentage: number | null
  truncations: {
    total_truncations: number
    messages_removed: number
    tokens_freed: number
  }
}

export type PenguinSession = Session & {
  agent_mode?: string
  agent_id?: string
  parent_agent_id?: string
  providerID?: string
  modelID?: string
  variant?: string
  message_count?: number
  display_message_count?: number
  fallback_title?: boolean
}

const PenguinSessionTimeSchema = z
  .object({
    created: z.number(),
    updated: z.number(),
    compacting: z.number().optional(),
    archived: z.number().optional(),
  })
  .passthrough()

export const PenguinSessionSchema = z
  .object({
    id: z.string(),
    title: z.string(),
    time: PenguinSessionTimeSchema,
    parentID: z.string().optional(),
    directory: z.string().optional(),
    agent_mode: z.string().optional(),
    agent_id: z.string().optional(),
    parent_agent_id: z.string().optional(),
    providerID: z.string().optional(),
    modelID: z.string().optional(),
    variant: z.string().optional(),
    message_count: z.number().optional(),
    display_message_count: z.number().optional(),
    fallback_title: z.boolean().optional(),
  })
  .passthrough()

export const PenguinSessionArraySchema = z.array(PenguinSessionSchema)

export function parsePenguinSessionArray(value: unknown): PenguinSession[] | undefined {
  if (!Array.isArray(value)) return undefined

  const sessions: PenguinSession[] = []
  for (const item of value) {
    const parsed = PenguinSessionSchema.safeParse(item)
    if (parsed.success) sessions.push(parsed.data as PenguinSession)
  }
  return sessions
}

export type PenguinBootstrapState = {
  agent: Agent[]
  command: Command[]
  config: Config
  path: Path
  provider: Provider[]
  provider_auth: Record<string, ProviderAuthMethod[]>
  provider_default: Record<string, string>
  provider_next: ProviderListResponse
  session: PenguinSession[]
  session_status: Record<string, SessionStatus>
  session_usage: Record<string, SessionUsage>
}

const SPARSE_PROVIDER_CATALOG_MODEL_LIMIT = 20

export function hasSparsePenguinProviderCatalog(
  providers: ReadonlyArray<{ models?: Record<string, unknown> | null }>,
): boolean {
  const modelCount = providers.reduce((total, provider) => total + Object.keys(provider.models ?? {}).length, 0)
  return modelCount > 0 && modelCount < SPARSE_PROVIDER_CATALOG_MODEL_LIMIT
}

export function parsePenguinUsage(raw: unknown): SessionUsage | undefined {
  if (typeof raw !== "object" || !raw) return undefined
  const root = raw as Record<string, unknown>
  const usage = typeof root.usage === "object" && root.usage ? (root.usage as Record<string, unknown>) : root

  const current = usage.current_total_tokens
  if (typeof current !== "number") return undefined

  const max = usage.max_context_window_tokens
  const available = usage.available_tokens
  const percentage = usage.percentage
  const trunc =
    typeof usage.truncations === "object" && usage.truncations ? (usage.truncations as Record<string, unknown>) : {}

  return {
    current_total_tokens: current,
    max_context_window_tokens: typeof max === "number" ? max : null,
    available_tokens: typeof available === "number" ? available : 0,
    percentage: typeof percentage === "number" ? percentage : null,
    truncations: {
      total_truncations: typeof trunc.total_truncations === "number" ? trunc.total_truncations : 0,
      messages_removed: typeof trunc.messages_removed === "number" ? trunc.messages_removed : 0,
      tokens_freed: typeof trunc.tokens_freed === "number" ? trunc.tokens_freed : 0,
    },
  }
}

export function unwrapBootstrapData(value: unknown): unknown {
  if (!value || typeof value !== "object") return value
  const record = value as Record<string, unknown>
  if (!("data" in record)) return value
  const keys = Object.keys(record)
  const wrapper = keys.every((key) => key === "data" || key === "meta")
  return wrapper ? record.data : value
}

function defaultPenguinCommands(): Command[] {
  return [
    {
      name: "config",
      description: "Show configuration sources",
      template: "/config",
      hints: [],
    },
    {
      name: "tool_details",
      description: "Toggle tool detail visibility",
      template: "/tool_details",
      hints: [],
    },
    {
      name: "thinking",
      description: "Toggle reasoning visibility",
      template: "/thinking",
      hints: [],
    },
  ]
}

function parsePenguinCommands(raw: unknown): Command[] | undefined {
  const data = unwrapBootstrapData(raw)
  if (!Array.isArray(data)) return

  const commands: Command[] = []
  for (const item of data) {
    if (!item || typeof item !== "object") continue
    const source = item as Record<string, unknown>
    const name = typeof source.name === "string" ? source.name.trim() : ""
    const template = typeof source.template === "string" ? source.template : `/${name}`
    if (!name || !template) continue
    if (source.enabled === false) continue
    const hints = Array.isArray(source.hints)
      ? source.hints.filter((hint): hint is string => typeof hint === "string")
      : []
    commands.push({
      name,
      description: typeof source.description === "string" ? source.description : undefined,
      source: source.source === "skill" || source.source === "mcp" ? source.source : "command",
      template,
      hints,
    })
  }

  return commands.length ? commands : undefined
}

function stamp(value: unknown, now: number): number {
  const time = typeof value === "string" ? Date.parse(value) : NaN
  return Number.isFinite(time) ? time : now
}

function providerListFromProviders(
  providers: Provider[],
  providerDefault: Record<string, string>,
): ProviderListResponse {
  const all: ProviderListResponse["all"] = providers.map((provider) => ({
    id: provider.id,
    name: provider.name,
    env: provider.env ?? [],
    models: Object.fromEntries(
      Object.entries(provider.models ?? {}).map(([id, model]) => [
        id,
        {
          id: model.id,
          name: model.name,
          release_date: model.release_date,
          attachment: model.capabilities?.attachment ?? false,
          reasoning: model.capabilities?.reasoning ?? false,
          temperature: model.capabilities?.temperature ?? false,
          tool_call: model.capabilities?.toolcall ?? false,
          limit: model.limit,
          status: model.status === "active" ? undefined : model.status,
          options: model.options ?? {},
        },
      ]),
    ),
  }))

  return {
    all,
    default: providerDefault,
    connected: providers.map((provider) => provider.id),
  }
}

function mapPenguinSession(input: { directory: string; item: Record<string, unknown>; now: number }): PenguinSession {
  const sid = typeof input.item.id === "string" ? input.item.id : crypto.randomUUID()
  const title = typeof input.item.title === "string" ? input.item.title : `Session ${sid.slice(-8)}`
  const time = input.item.time
  const created =
    typeof time === "object" && time && "created" in time && typeof time.created === "number"
      ? time.created
      : stamp(input.item.created_at, input.now)
  const updated =
    typeof time === "object" && time && "updated" in time && typeof time.updated === "number"
      ? time.updated
      : stamp(input.item.last_active, input.now)
  const directoryValue = typeof input.item.directory === "string" ? input.item.directory : input.directory
  const payload: PenguinSession = {
    id: sid,
    slug: typeof input.item.slug === "string" ? input.item.slug : sid,
    projectID: typeof input.item.projectID === "string" ? input.item.projectID : "penguin",
    directory: directoryValue,
    title,
    version: typeof input.item.version === "string" ? input.item.version : "penguin",
    time: {
      created,
      updated,
    },
  }
  const parentID = typeof input.item.parentID === "string" ? input.item.parentID : undefined
  if (parentID) payload.parentID = parentID
  const permission = Array.isArray(input.item.permission) ? input.item.permission : undefined
  if (permission) payload.permission = permission as Session["permission"]
  const share = input.item.share
  if (share && typeof share === "object" && typeof (share as { url?: unknown }).url === "string") {
    payload.share = { url: (share as { url: string }).url }
  }
  const summary = input.item.summary
  if (summary && typeof summary === "object") {
    const source = summary as Record<string, unknown>
    if (
      typeof source.additions === "number" &&
      typeof source.deletions === "number" &&
      typeof source.files === "number"
    ) {
      payload.summary = {
        additions: source.additions,
        deletions: source.deletions,
        files: source.files,
        diffs: Array.isArray(source.diffs)
          ? (source.diffs as Session["summary"] extends { diffs?: infer T } ? T : never)
          : undefined,
      }
    }
  }
  const revert = input.item.revert
  if (revert && typeof revert === "object" && typeof (revert as { messageID?: unknown }).messageID === "string") {
    const source = revert as Record<string, unknown>
    payload.revert = {
      messageID: String(source.messageID),
      ...(typeof source.partID === "string" ? { partID: source.partID } : {}),
      ...(typeof source.snapshot === "string" ? { snapshot: source.snapshot } : {}),
      ...(typeof source.diff === "string" ? { diff: source.diff } : {}),
    }
  }
  const sessionMode = typeof input.item.agent_mode === "string" ? input.item.agent_mode : undefined
  if (sessionMode) payload.agent_mode = sessionMode
  const providerID = typeof input.item.providerID === "string" ? input.item.providerID : undefined
  if (providerID) payload.providerID = providerID
  const modelID = typeof input.item.modelID === "string" ? input.item.modelID : undefined
  if (modelID) payload.modelID = modelID
  const variant = typeof input.item.variant === "string" ? input.item.variant : undefined
  if (variant) payload.variant = variant
  const messageCount = typeof input.item.message_count === "number" ? input.item.message_count : undefined
  if (messageCount !== undefined) payload.message_count = messageCount
  const displayMessageCount =
    typeof input.item.display_message_count === "number" ? input.item.display_message_count : undefined
  if (displayMessageCount !== undefined) payload.display_message_count = displayMessageCount
  const fallbackTitle = typeof input.item.fallback_title === "boolean" ? input.item.fallback_title : undefined
  if (fallbackTitle !== undefined) payload.fallback_title = fallbackTitle
  const agentID = typeof input.item.agent_id === "string" ? input.item.agent_id : undefined
  if (agentID) payload.agent_id = agentID
  const parentAgentID = typeof input.item.parent_agent_id === "string" ? input.item.parent_agent_id : undefined
  if (parentAgentID) payload.parent_agent_id = parentAgentID
  return payload
}

function mapPenguinAgent(item: Record<string, unknown>): Agent | undefined {
  const name = typeof item.id === "string" ? item.id : ""
  if (!name) return undefined
  const mode = item.is_sub_agent === true ? ("subagent" as const) : ("primary" as const)
  const hidden = item.hidden === true
  const permission = Array.isArray(item.permission) ? item.permission : []
  const rawOptions = item.options
  const options =
    rawOptions && typeof rawOptions === "object"
      ? ({ ...rawOptions } as Record<string, unknown>)
      : ({} as Record<string, unknown>)
  const sessionMode = typeof item.agent_mode === "string" ? item.agent_mode : undefined
  if (sessionMode && !options.agent_mode) options.agent_mode = sessionMode
  return {
    name,
    mode,
    hidden,
    permission,
    options,
  }
}

export function mapPenguinBootstrap(input: {
  baseUrl: string | URL
  commandsData?: unknown
  configData: unknown
  directory: string
  now?: number
  providerAuthData: unknown
  providerListData: unknown
  providersData: unknown
  roster: Record<string, unknown>[]
  sessions: Record<string, unknown>[]
}): PenguinBootstrapState {
  const now = input.now ?? Date.now()

  const providersPayload = unwrapBootstrapData(input.providersData) as Record<string, unknown> | undefined
  const providerListPayload = unwrapBootstrapData(input.providerListData) as Record<string, unknown> | undefined
  const configPayload = unwrapBootstrapData(input.configData)
  const providerAuthPayload = unwrapBootstrapData(input.providerAuthData)

  const providers: Provider[] = Array.isArray(providersPayload?.providers)
    ? (providersPayload.providers as Provider[])
    : []
  const providerDefault =
    providersPayload && typeof providersPayload.default === "object" && providersPayload.default
      ? (providersPayload.default as Record<string, string>)
      : {}
  const providerNext =
    providerListPayload &&
    Array.isArray(providerListPayload.all) &&
    providerListPayload.default &&
    Array.isArray(providerListPayload.connected)
      ? (providerListPayload as ProviderListResponse)
      : providerListFromProviders(providers, providerDefault)
  const providerAuth =
    providerAuthPayload && typeof providerAuthPayload === "object"
      ? (providerAuthPayload as Record<string, ProviderAuthMethod[]>)
      : {}
  const config: Config =
    configPayload && typeof configPayload === "object" ? (configPayload as Config) : { share: "disabled" as const }
  const session = input.sessions.map((item) =>
    mapPenguinSession({
      directory: input.directory,
      item,
      now,
    }),
  )
  const sessionUsage = input.sessions.reduce<Record<string, SessionUsage>>(
    (acc, item) => {
      const sid = typeof item.id === "string" ? item.id : ""
      if (!sid) return acc
      const next = parsePenguinUsage(item)
      if (!next) return acc
      acc[sid] = next
      return acc
    },
    {} as Record<string, SessionUsage>,
  )
  const baseAgent: Agent = {
    name: "penguin",
    mode: "primary",
    permission: [],
    options: {},
  }
  const agent = input.roster.map(mapPenguinAgent).filter((item): item is Agent => !!item)
  const command = parsePenguinCommands(input.commandsData) ?? defaultPenguinCommands()
  const sessionStatus = Object.fromEntries(session.map((item) => [item.id, { type: "idle" as const }]))

  return {
    provider: providers,
    provider_default: providerDefault,
    provider_next: providerNext,
    provider_auth: providerAuth,
    agent: agent.length ? agent : [baseAgent],
    command,
    config,
    session,
    session_usage: sessionUsage,
    session_status: sessionStatus,
    path: { state: "", config: "", worktree: "", directory: input.directory },
  }
}

export function createPenguinBootstrapFallback(input: {
  baseUrl: string | URL
  directory: string
  now?: number
}): PenguinBootstrapState {
  return mapPenguinBootstrap({
    baseUrl: input.baseUrl,
    configData: undefined,
    directory: input.directory,
    now: input.now,
    providerAuthData: undefined,
    providerListData: undefined,
    providersData: undefined,
    roster: [],
    sessions: [],
  })
}

export async function fetchBootstrapJson<T>(input: {
  fetch: BootstrapFetch
  path: string | URL
  endpoint: string
  fallback: T
  required?: boolean
}): Promise<T> {
  try {
    const res = await input.fetch(input.path)
    if (res.ok) {
      return res.json().catch(() => input.fallback)
    }

    const details = await res.text().catch(() => "")
    const error = new Error(
      details ? `Bootstrap request failed (${res.status}): ${details}` : `Bootstrap request failed (${res.status})`,
    )
    if (input.required) throw error
    Log.Default.warn("penguin bootstrap degraded", {
      endpoint: input.endpoint,
      status: res.status,
      details: details || undefined,
    })
    return input.fallback
  } catch (error) {
    if (input.required) throw error
    Log.Default.warn("penguin bootstrap degraded", {
      endpoint: input.endpoint,
      error: error instanceof Error ? error.message : String(error),
    })
    return input.fallback
  }
}
