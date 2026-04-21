import type {
  Agent,
  Command,
  Config,
  FormatterStatus,
  LspStatus,
  Path,
  Provider,
  ProviderAuthMethod,
  ProviderListResponse,
  Session,
  SessionStatus,
  VcsInfo,
} from "@opencode-ai/sdk/v2"
import fs from "fs"
import path from "path"
import { iife } from "@/util/iife"
import { fetchBootstrapJson } from "./sync-bootstrap"

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
}

export type PenguinBootstrapState = {
  provider: Provider[]
  provider_default: Record<string, string>
  provider_next: ProviderListResponse
  provider_auth: Record<string, ProviderAuthMethod[]>
  agent: Agent[]
  command: Command[]
  config: Config
  session: PenguinSession[]
  session_usage: Record<string, SessionUsage>
  session_status: Record<string, SessionStatus>
  lsp: LspStatus[]
  formatter: FormatterStatus[]
  vcs: VcsInfo | undefined
  path: Path
}

type PenguinEvent = {
  type: string
  properties: unknown
}

type BootstrapFetch = (input: string | URL, init?: RequestInit) => Promise<Response>

export function parsePenguinSessionUsage(raw: unknown): SessionUsage | undefined {
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

export function normalizePenguinDirectory(value?: string): string | undefined {
  if (!value || typeof value !== "string") return undefined
  const trimmed = value.trim()
  if (!trimmed) return undefined
  const resolved = iife(() => {
    try {
      if (fs.realpathSync.native) return fs.realpathSync.native(trimmed)
    } catch {
      // no-op
    }
    try {
      return fs.realpathSync(trimmed)
    } catch {
      // no-op
    }
    try {
      return path.resolve(trimmed)
    } catch {
      return trimmed
    }
  })
  return resolved.replace(/\\/g, "/")
}

export function getPenguinEventSessionID(event: PenguinEvent): string | undefined {
  const props = event.properties
  if (!props || typeof props !== "object") return undefined
  const root = props as Record<string, unknown>
  const direct = root.sessionID ?? root.session_id ?? root.conversation_id
  if (typeof direct === "string" && direct) return direct
  const info = root.info
  if (info && typeof info === "object") {
    const infoSession =
      (info as Record<string, unknown>).sessionID ??
      (info as Record<string, unknown>).session_id ??
      (info as Record<string, unknown>).conversation_id
    if (typeof infoSession === "string" && infoSession) return infoSession
  }
  const part = root.part
  if (part && typeof part === "object") {
    const partSession =
      (part as Record<string, unknown>).sessionID ??
      (part as Record<string, unknown>).session_id ??
      (part as Record<string, unknown>).conversation_id
    if (typeof partSession === "string" && partSession) return partSession
  }
  return undefined
}

export function getPenguinEventDirectory(event: PenguinEvent): string | undefined {
  const props = event.properties
  if (!props || typeof props !== "object") return undefined
  const root = props as Record<string, unknown>
  if (typeof root.directory === "string" && root.directory) return root.directory
  const info = root.info
  if (info && typeof info === "object") {
    const infoRoot = info as Record<string, unknown>
    if (typeof infoRoot.directory === "string" && infoRoot.directory) return infoRoot.directory
    const pathRoot = infoRoot.path
    if (pathRoot && typeof pathRoot === "object") {
      const cwd = (pathRoot as Record<string, unknown>).cwd
      if (typeof cwd === "string" && cwd) return cwd
    }
  }
  const pathRoot = root.path
  if (pathRoot && typeof pathRoot === "object") {
    const cwd = (pathRoot as Record<string, unknown>).cwd
    if (typeof cwd === "string" && cwd) return cwd
  }
  const part = root.part
  if (part && typeof part === "object") {
    const partRoot = part as Record<string, unknown>
    if (typeof partRoot.directory === "string" && partRoot.directory) return partRoot.directory
  }
  return undefined
}

export function shouldProcessPenguinEvent(input: {
  event: PenguinEvent
  activeSessionID?: string
  appDirectory?: string
  sessionDirectory: (sessionID?: string) => string | undefined
}): boolean {
  const sid = getPenguinEventSessionID(input.event)
  const dir = normalizePenguinDirectory(getPenguinEventDirectory(input.event))
  const baseDir = input.appDirectory
  const isDirectorylessSystemEvent =
    !dir &&
    (input.event.type === "lsp.updated" ||
      input.event.type === "lsp.client.diagnostics" ||
      input.event.type === "vcs.branch.updated")

  if (input.activeSessionID) {
    if (sid && sid !== input.activeSessionID) return false
    const activeDir = input.sessionDirectory(input.activeSessionID) ?? baseDir
    if (!sid) {
      if (dir && activeDir && dir !== activeDir) return false
      if (isDirectorylessSystemEvent) return false
    }
    return true
  }

  if (sid) {
    const sidDir = input.sessionDirectory(sid)
    if (sidDir && baseDir && sidDir !== baseDir) return false
    if (!sidDir && dir && baseDir && dir !== baseDir) return false
  }
  if (!sid) {
    if (dir && baseDir && dir !== baseDir) return false
    if (isDirectorylessSystemEvent) return false
  }

  return true
}

export async function fetchPenguinSessionUsage(input: {
  fetch: BootstrapFetch
  url: string
  sessionID: string
}): Promise<SessionUsage | undefined> {
  const target = new URL(`/session/${encodeURIComponent(input.sessionID)}`, input.url)
  const data = await input.fetch(target).then((res) => (res.ok ? res.json() : undefined))
  return parsePenguinSessionUsage(data)
}

function unwrapBootstrapData<T>(value: T): T {
  if (!value || typeof value !== "object") return value
  const record = value as Record<string, unknown>
  if (!("data" in record)) return value
  const keys = Object.keys(record)
  const wrapper = keys.every((key) => key === "data" || key === "meta")
  return (wrapper ? record.data : value) as T
}

function stampTime(value: unknown, fallback: number): number {
  const parsed = typeof value === "string" ? Date.parse(value) : Number.NaN
  return Number.isFinite(parsed) ? parsed : fallback
}

function defaultPenguinModel(now: number, url: string) {
  return {
    id: "penguin-default",
    providerID: "penguin",
    api: {
      id: "penguin-web",
      url,
      npm: "penguin",
    },
    name: "Penguin Default",
    capabilities: {
      temperature: true,
      reasoning: true,
      attachment: false,
      toolcall: false,
      input: {
        text: true,
        audio: false,
        image: false,
        video: false,
        pdf: false,
      },
      output: {
        text: true,
        audio: false,
        image: false,
        video: false,
        pdf: false,
      },
      interleaved: false,
    },
    cost: {
      input: 0,
      output: 0,
      cache: { read: 0, write: 0 },
    },
    limit: {
      context: 100000,
      output: 4096,
    },
    status: "beta" as const,
    options: {},
    headers: {},
    release_date: new Date(now).toISOString(),
  }
}

function defaultPenguinProvider(now: number, url: string) {
  const model = defaultPenguinModel(now, url)
  return {
    provider: {
      id: "penguin",
      name: "Penguin",
      source: "custom" as const,
      env: [],
      options: {},
      models: {
        [model.id]: model,
      },
    },
    model,
  }
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

function defaultPenguinPath(directory: string): Path {
  return {
    home: "",
    state: "",
    config: "",
    worktree: "",
    directory,
  }
}

function mapPenguinSessions(input: {
  list: Array<Record<string, unknown>>
  directory: string
  now: number
}): PenguinSession[] {
  return input.list.map((item) => {
    const sid = typeof item.id === "string" ? item.id : crypto.randomUUID()
    const title = typeof item.title === "string" ? item.title : `Session ${sid.slice(-8)}`
    const time = item.time
    const created =
      typeof time === "object" && time && "created" in time && typeof time.created === "number"
        ? time.created
        : stampTime(item.created_at, input.now)
    const updated =
      typeof time === "object" && time && "updated" in time && typeof time.updated === "number"
        ? time.updated
        : stampTime(item.last_active, input.now)
    const directoryValue = typeof item.directory === "string" ? item.directory : input.directory
    const payload: PenguinSession = {
      id: sid,
      slug: typeof item.slug === "string" ? item.slug : sid,
      projectID: typeof item.projectID === "string" ? item.projectID : "penguin",
      directory: directoryValue,
      title,
      version: typeof item.version === "string" ? item.version : "penguin",
      time: {
        created,
        updated,
      },
    }

    const parentID = typeof item.parentID === "string" ? item.parentID : undefined
    if (parentID) payload.parentID = parentID

    const permission = Array.isArray(item.permission) ? item.permission : undefined
    if (permission) payload.permission = permission as Session["permission"]

    const share = item.share
    if (share && typeof share === "object" && typeof (share as { url?: unknown }).url === "string") {
      payload.share = { url: (share as { url: string }).url }
    }

    const summary = item.summary
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

    const revert = item.revert
    if (revert && typeof revert === "object" && typeof (revert as { messageID?: unknown }).messageID === "string") {
      const source = revert as Record<string, unknown>
      payload.revert = {
        messageID: String(source.messageID),
        ...(typeof source.partID === "string" ? { partID: source.partID } : {}),
        ...(typeof source.snapshot === "string" ? { snapshot: source.snapshot } : {}),
        ...(typeof source.diff === "string" ? { diff: source.diff } : {}),
      }
    }

    const sessionMode = typeof item.agent_mode === "string" ? item.agent_mode : undefined
    if (sessionMode) payload.agent_mode = sessionMode

    const providerID = typeof item.providerID === "string" ? item.providerID : undefined
    if (providerID) payload.providerID = providerID

    const modelID = typeof item.modelID === "string" ? item.modelID : undefined
    if (modelID) payload.modelID = modelID

    const variant = typeof item.variant === "string" ? item.variant : undefined
    if (variant) payload.variant = variant

    const agentID = typeof item.agent_id === "string" ? item.agent_id : undefined
    if (agentID) payload.agent_id = agentID

    const parentAgentID = typeof item.parent_agent_id === "string" ? item.parent_agent_id : undefined
    if (parentAgentID) payload.parent_agent_id = parentAgentID

    return payload
  })
}

function mapPenguinAgents(roster: Array<Record<string, unknown>>): Agent[] {
  const agents = roster
    .map((item) => {
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
    })
    .filter((item) => !!item)

  if (agents.length > 0) return agents
  return [
    {
      name: "penguin",
      mode: "primary" as const,
      permission: [],
      options: {},
    },
  ]
}

export async function bootstrapPenguinState(input: {
  fetch: BootstrapFetch
  url: string
  directory: string
}): Promise<PenguinBootstrapState> {
  const now = Date.now()
  const { provider: fallbackProvider, model: fallbackModel } = defaultPenguinProvider(now, input.url)
  const sessionsUrl = new URL("/session", input.url)
  sessionsUrl.searchParams.set("directory", input.directory)
  sessionsUrl.searchParams.set("limit", "50")

  const [providersData, providerListData, configData, providerAuthData, sessionsData, roster, lsp, formatter, vcs, pathData] =
    await Promise.all([
      fetchBootstrapJson({
        fetch: input.fetch,
        path: new URL("/config/providers", input.url),
        endpoint: "/config/providers",
        fallback: undefined,
      }),
      fetchBootstrapJson({
        fetch: input.fetch,
        path: new URL("/provider", input.url),
        endpoint: "/provider",
        fallback: undefined,
      }),
      fetchBootstrapJson({
        fetch: input.fetch,
        path: new URL("/config", input.url),
        endpoint: "/config",
        fallback: undefined,
      }),
      fetchBootstrapJson({
        fetch: input.fetch,
        path: new URL("/provider/auth", input.url),
        endpoint: "/provider/auth",
        fallback: undefined,
      }),
      input.fetch(sessionsUrl)
        .then((res) => (res.ok ? res.json() : undefined))
        .then((data) => (Array.isArray(data) ? data : []))
        .catch(() => []),
      input.fetch(new URL("/api/v1/agents", input.url))
        .then((res) => (res.ok ? res.json() : undefined))
        .then((data) => (Array.isArray(data) ? data : []))
        .catch(() => []),
      fetchBootstrapJson({
        fetch: input.fetch,
        path: new URL(`/lsp?directory=${encodeURIComponent(input.directory)}`, input.url),
        endpoint: "/lsp",
        fallback: [] as LspStatus[],
      }),
      fetchBootstrapJson({
        fetch: input.fetch,
        path: new URL(`/formatter?directory=${encodeURIComponent(input.directory)}`, input.url),
        endpoint: "/formatter",
        fallback: [] as FormatterStatus[],
      }),
      fetchBootstrapJson({
        fetch: input.fetch,
        path: new URL(`/vcs?directory=${encodeURIComponent(input.directory)}`, input.url),
        endpoint: "/vcs",
        fallback: undefined,
      }),
      fetchBootstrapJson({
        fetch: input.fetch,
        path: new URL(`/path?directory=${encodeURIComponent(input.directory)}`, input.url),
        endpoint: "/path",
        fallback: undefined,
      }),
    ])

  const list = sessionsData as Array<Record<string, unknown>>
  const providersPayload = unwrapBootstrapData(providersData) as Record<string, unknown> | undefined
  const providerListPayload = unwrapBootstrapData(providerListData) as Record<string, unknown> | undefined
  const configPayload = unwrapBootstrapData(configData)
  const providerAuthPayload = unwrapBootstrapData(providerAuthData)

  const providers = Array.isArray(providersPayload?.providers) ? providersPayload.providers : [fallbackProvider]
  const providerDefault =
    providersPayload && typeof providersPayload.default === "object" && providersPayload.default
      ? (providersPayload.default as Record<string, string>)
      : { [fallbackProvider.id]: fallbackModel.id }
  const providerNext =
    providerListPayload &&
    Array.isArray(providerListPayload.all) &&
    providerListPayload.default &&
    Array.isArray(providerListPayload.connected)
      ? (providerListPayload as ProviderListResponse)
      : {
          all: [
            {
              id: fallbackProvider.id,
              name: fallbackProvider.name,
              env: fallbackProvider.env,
              models: {
                [fallbackModel.id]: {
                  id: fallbackModel.id,
                  name: fallbackModel.name,
                  release_date: fallbackModel.release_date,
                  attachment: fallbackModel.capabilities.attachment,
                  reasoning: fallbackModel.capabilities.reasoning,
                  temperature: fallbackModel.capabilities.temperature,
                  tool_call: fallbackModel.capabilities.toolcall,
                  limit: fallbackModel.limit,
                  status: fallbackModel.status,
                  options: {},
                },
              },
            },
          ],
          default: { [fallbackProvider.id]: fallbackModel.id },
          connected: [fallbackProvider.id],
        }
  const providerAuth =
    providerAuthPayload && typeof providerAuthPayload === "object"
      ? (providerAuthPayload as Record<string, ProviderAuthMethod[]>)
      : {}
  const config = configPayload && typeof configPayload === "object" ? (configPayload as Config) : { share: "disabled" }
  const session = mapPenguinSessions({ list, directory: input.directory, now })
  const sessionUsage = list.reduce(
    (acc: Record<string, SessionUsage>, item) => {
      const sid = typeof item.id === "string" ? item.id : ""
      if (!sid) return acc
      const next = parsePenguinSessionUsage(item)
      if (!next) return acc
      acc[sid] = next
      return acc
    },
    {},
  )
  const sessionStatus = Object.fromEntries(session.map((item) => [item.id, { type: "idle" as const }]))

  return {
    provider: providers,
    provider_default: providerDefault,
    provider_next: providerNext,
    provider_auth: providerAuth,
    agent: mapPenguinAgents(roster as Array<Record<string, unknown>>),
    command: defaultPenguinCommands(),
    config,
    session,
    session_usage: sessionUsage,
    session_status: sessionStatus,
    lsp: Array.isArray(lsp) ? lsp : [],
    formatter: Array.isArray(formatter) ? formatter : [],
    vcs: vcs as VcsInfo | undefined,
    path: (pathData as Path | undefined) ?? defaultPenguinPath(input.directory),
  }
}
