import type {
  Message,
  Agent,
  Provider,
  Session,
  Part,
  Config,
  Todo,
  Command,
  PermissionRequest,
  QuestionRequest,
  LspStatus,
  McpStatus,
  McpResource,
  FormatterStatus,
  SessionStatus,
  ProviderListResponse,
  ProviderAuthMethod,
  VcsInfo,
} from "@opencode-ai/sdk/v2"
import fs from "fs"
import path from "path"
import { createStore, produce, reconcile } from "solid-js/store"
import { useSDK } from "@tui/context/sdk"
import { Binary } from "@opencode-ai/util/binary"
import { createSimpleContext } from "./helper"
import type { Snapshot } from "@/snapshot"
import { useExit } from "./exit"
import { useArgs } from "./args"
import { batch, onMount } from "solid-js"
import { Log } from "@/util/log"
import { iife } from "@/util/iife"
import type { Path } from "@opencode-ai/sdk"
import { hydrateSessionSnapshot, mergeHydratedMessages } from "./session-hydration"

type SessionUsage = {
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

const parseUsage = (raw: unknown): SessionUsage | undefined => {
  if (typeof raw !== "object" || !raw) return undefined
  const root = raw as Record<string, unknown>
  const usage =
    typeof root.usage === "object" && root.usage
      ? (root.usage as Record<string, unknown>)
      : root

  const current = usage.current_total_tokens
  if (typeof current !== "number") return undefined

  const max = usage.max_context_window_tokens
  const available = usage.available_tokens
  const percentage = usage.percentage
  const trunc =
    typeof usage.truncations === "object" && usage.truncations
      ? (usage.truncations as Record<string, unknown>)
      : {}

  return {
    current_total_tokens: current,
    max_context_window_tokens: typeof max === "number" ? max : null,
    available_tokens: typeof available === "number" ? available : 0,
    percentage: typeof percentage === "number" ? percentage : null,
    truncations: {
      total_truncations:
        typeof trunc.total_truncations === "number" ? trunc.total_truncations : 0,
      messages_removed:
        typeof trunc.messages_removed === "number" ? trunc.messages_removed : 0,
      tokens_freed: typeof trunc.tokens_freed === "number" ? trunc.tokens_freed : 0,
    },
  }
}

export const { use: useSync, provider: SyncProvider } = createSimpleContext({
  name: "Sync",
  init: () => {
    const [store, setStore] = createStore<{
      status: "loading" | "partial" | "complete"
      provider: Provider[]
      provider_default: Record<string, string>
      provider_next: ProviderListResponse
      provider_auth: Record<string, ProviderAuthMethod[]>
      agent: Agent[]
      command: Command[]
      permission: {
        [sessionID: string]: PermissionRequest[]
      }
      question: {
        [sessionID: string]: QuestionRequest[]
      }
      config: Config
      session: Session[]
      session_status: {
        [sessionID: string]: SessionStatus
      }
      session_usage: {
        [sessionID: string]: SessionUsage
      }
      session_diff: {
        [sessionID: string]: Snapshot.FileDiff[]
      }
      todo: {
        [sessionID: string]: Todo[]
      }
      message: {
        [sessionID: string]: Message[]
      }
      part: {
        [messageID: string]: Part[]
      }
      lsp: LspStatus[]
      mcp: {
        [key: string]: McpStatus
      }
      mcp_resource: {
        [key: string]: McpResource
      }
      formatter: FormatterStatus[]
      vcs: VcsInfo | undefined
      path: Path
    }>({
      provider_next: {
        all: [],
        default: {},
        connected: [],
      },
      provider_auth: {},
      config: {},
      status: "loading",
      agent: [],
      permission: {},
      question: {},
      command: [],
      provider: [],
      provider_default: {},
      session: [],
      session_status: {},
      session_usage: {},
      session_diff: {},
      todo: {},
      message: {},
      part: {},
      lsp: [],
      mcp: {},
      mcp_resource: {},
      formatter: [],
      vcs: undefined,
      path: { state: "", config: "", worktree: "", directory: "" },
    })

    const sdk = useSDK()

    const normalizeDirectory = (value?: string) => {
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

    const resolveDirectory = (sessionID?: string) => {
      if (sessionID) {
        const session = store.session.find((item) => item.id === sessionID)
        if (session?.directory) return session.directory
      }
      if (store.path.directory) return store.path.directory
      if (sdk.directory) return sdk.directory
      return process.cwd()
    }

    const appDirectory = () => normalizeDirectory(resolveDirectory())

    const sessionDirectory = (sessionID?: string) => {
      if (!sessionID) return undefined
      const session = store.session.find((item) => item.id === sessionID)
      return normalizeDirectory(session?.directory)
    }

    const eventSessionID = (event: { properties: unknown }) => {
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

    const eventDirectory = (event: { properties: unknown }) => {
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

    const usageRefreshInFlight = new Set<string>()
    const usageRefreshAt = new Map<string, number>()

    const refreshSessionUsage = (sessionID: string) => {
      if (!sdk.penguin || !sessionID) return
      const baseDir = appDirectory()
      const sessionDir = sessionDirectory(sessionID)
      if (sessionDir && baseDir && sessionDir !== baseDir) return
      if (!store.session.some((item) => item.id === sessionID)) return
      const now = Date.now()
      const last = usageRefreshAt.get(sessionID) ?? 0
      if (usageRefreshInFlight.has(sessionID) || now - last < 400) return
      usageRefreshInFlight.add(sessionID)
      usageRefreshAt.set(sessionID, now)
      const url = new URL(`/session/${encodeURIComponent(sessionID)}`, sdk.url)
      fetch(url)
        .then((res) => (res.ok ? res.json() : undefined))
        .then((data) => {
          const usage = parseUsage(data)
          if (!usage) return
          setStore("session_usage", sessionID, reconcile(usage))
        })
        .catch(() => undefined)
        .finally(() => {
          usageRefreshInFlight.delete(sessionID)
        })
    }

    sdk.event.listen((e) => {
      const event = e.details
      if (sdk.penguin) {
        const sid = eventSessionID(event)
        const dir = normalizeDirectory(eventDirectory(event))
        const baseDir = appDirectory()
        if (sid) {
          const sidDir = sessionDirectory(sid)
          if (sidDir && baseDir && sidDir !== baseDir) return
          if (!sidDir && dir && baseDir && dir !== baseDir) return
        }
        if (!sid) {
          if (dir && baseDir && dir !== baseDir) return
          if (
            !dir &&
            (event.type === "lsp.updated" ||
              event.type === "lsp.client.diagnostics" ||
              event.type === "vcs.branch.updated")
          ) {
            return
          }
        }
      }
      switch (event.type) {
        case "server.instance.disposed":
          bootstrap()
          break
        case "permission.replied": {
          const requests = store.permission[event.properties.sessionID]
          if (!requests) break
          const match = Binary.search(requests, event.properties.requestID, (r) => r.id)
          if (!match.found) break
          setStore(
            "permission",
            event.properties.sessionID,
            produce((draft) => {
              draft.splice(match.index, 1)
            }),
          )
          break
        }

        case "permission.asked": {
          const request = event.properties
          const requests = store.permission[request.sessionID]
          if (!requests) {
            setStore("permission", request.sessionID, [request])
            break
          }
          const match = Binary.search(requests, request.id, (r) => r.id)
          if (match.found) {
            setStore("permission", request.sessionID, match.index, reconcile(request))
            break
          }
          setStore(
            "permission",
            request.sessionID,
            produce((draft) => {
              draft.splice(match.index, 0, request)
            }),
          )
          break
        }

        case "question.replied":
        case "question.rejected": {
          const requests = store.question[event.properties.sessionID]
          if (!requests) break
          const match = Binary.search(requests, event.properties.requestID, (r) => r.id)
          if (!match.found) break
          setStore(
            "question",
            event.properties.sessionID,
            produce((draft) => {
              draft.splice(match.index, 1)
            }),
          )
          break
        }

        case "question.asked": {
          const request = event.properties
          const requests = store.question[request.sessionID]
          if (!requests) {
            setStore("question", request.sessionID, [request])
            break
          }
          const match = Binary.search(requests, request.id, (r) => r.id)
          if (match.found) {
            setStore("question", request.sessionID, match.index, reconcile(request))
            break
          }
          setStore(
            "question",
            request.sessionID,
            produce((draft) => {
              draft.splice(match.index, 0, request)
            }),
          )
          break
        }

        case "todo.updated":
          setStore("todo", event.properties.sessionID, event.properties.todos)
          break

        case "session.diff":
          setStore("session_diff", event.properties.sessionID, event.properties.diff)
          break

        case "session.deleted": {
          const result = Binary.search(store.session, event.properties.info.id, (s) => s.id)
          if (result.found) {
            setStore(
              "session",
              produce((draft) => {
                draft.splice(result.index, 1)
              }),
            )
          }
          break
        }
        case "session.updated": {
          const result = Binary.search(store.session, event.properties.info.id, (s) => s.id)
          if (result.found) {
            setStore("session", result.index, reconcile(event.properties.info))
            break
          }
          setStore(
            "session",
            produce((draft) => {
              draft.splice(result.index, 0, event.properties.info)
            }),
          )
          break
        }

        case "session.status": {
          setStore("session_status", event.properties.sessionID, event.properties.status)
          if (sdk.penguin && event.properties.status.type === "idle") {
            refreshSessionUsage(event.properties.sessionID)
          }
          break
        }

        case "message.updated": {
          const info = "info" in event.properties ? event.properties.info : event.properties
          if (!info || !("sessionID" in info)) break
          const normalized =
            info.role === "assistant"
              ? {
                  ...info,
                  parentID: info.parentID ?? "root",
                  agent: info.agent ?? "penguin",
                  path:
                    info.path ??
                    ({
                      cwd: process.cwd(),
                      root: process.cwd(),
                    } as const),
                  modelID: info.modelID ?? "penguin-default",
                  providerID: info.providerID ?? "penguin",
                  mode: info.mode ?? "chat",
                }
              : info
          const messages = store.message[normalized.sessionID]
          if (!messages) {
            setStore("message", normalized.sessionID, [normalized])
            break
          }
          if (sdk.penguin) {
            const match = messages.findIndex((item) => item.id === normalized.id)
            if (match !== -1) {
              setStore("message", normalized.sessionID, match, reconcile(normalized))
              if (
                normalized.role === "assistant" &&
                typeof normalized.time === "object" &&
                !!normalized.time?.completed
              ) {
                refreshSessionUsage(normalized.sessionID)
              }
              break
            }
            setStore(
              "message",
              normalized.sessionID,
              produce((draft) => {
                draft.push(normalized)
              }),
            )
            const updated = store.message[normalized.sessionID]
            if (updated.length > 100) {
              const oldest = updated[0]
              batch(() => {
                setStore(
                  "message",
                  normalized.sessionID,
                  produce((draft) => {
                    draft.shift()
                  }),
                )
                setStore(
                  "part",
                  produce((draft) => {
                    delete draft[oldest.id]
                  }),
                )
              })
            }
            if (
              normalized.role === "assistant" &&
              typeof normalized.time === "object" &&
              !!normalized.time?.completed
            ) {
              refreshSessionUsage(normalized.sessionID)
            }
            break
          }
          const result = Binary.search(messages, normalized.id, (m) => m.id)
          if (result.found) {
            setStore("message", normalized.sessionID, result.index, reconcile(normalized))
            break
          }
          setStore(
            "message",
            normalized.sessionID,
            produce((draft) => {
              draft.splice(result.index, 0, normalized)
            }),
          )
          const updated = store.message[normalized.sessionID]
          if (updated.length > 100) {
            const oldest = updated[0]
            batch(() => {
              setStore(
                "message",
                normalized.sessionID,
                produce((draft) => {
                  draft.shift()
                }),
              )
              setStore(
                "part",
                produce((draft) => {
                  delete draft[oldest.id]
                }),
              )
            })
          }
          if (
            normalized.role === "assistant" &&
            typeof normalized.time === "object" &&
            !!normalized.time?.completed
          ) {
            refreshSessionUsage(normalized.sessionID)
          }
          break
        }
        case "message.removed": {
          const messages = store.message[event.properties.sessionID]
          const result = Binary.search(messages, event.properties.messageID, (m) => m.id)
          if (result.found) {
            setStore(
              "message",
              event.properties.sessionID,
              produce((draft) => {
                draft.splice(result.index, 1)
              }),
            )
          }
          break
        }
        case "message.part.updated": {
          const parts = store.part[event.properties.part.messageID]
          if (!parts) {
            setStore("part", event.properties.part.messageID, [event.properties.part])
            break
          }
          const result = Binary.search(parts, event.properties.part.id, (p) => p.id)
          if (result.found) {
            setStore("part", event.properties.part.messageID, result.index, reconcile(event.properties.part))
            break
          }
          setStore(
            "part",
            event.properties.part.messageID,
            produce((draft) => {
              draft.splice(result.index, 0, event.properties.part)
            }),
          )
          break
        }

        case "message.part.removed": {
          const parts = store.part[event.properties.messageID]
          const result = Binary.search(parts, event.properties.partID, (p) => p.id)
          if (result.found)
            setStore(
              "part",
              event.properties.messageID,
              produce((draft) => {
                draft.splice(result.index, 1)
              }),
            )
          break
        }

        case "lsp.updated": {
          if (sdk.penguin) {
            const sid = eventSessionID(event)
            const scopedDirectory = eventDirectory(event) ?? resolveDirectory(sid)
            const normalizedScoped = normalizeDirectory(scopedDirectory)
            const normalizedBase = appDirectory()
            if (!scopedDirectory) break
            if (normalizedScoped && normalizedBase && normalizedScoped !== normalizedBase) break
            const url = new URL("/lsp", sdk.url)
            url.searchParams.set("directory", scopedDirectory)
            fetch(url)
              .then((res) => (res.ok ? res.json() : []))
              .then((data) => setStore("lsp", reconcile(Array.isArray(data) ? data : [])))
              .catch(() => undefined)
            break
          }
          sdk.client.lsp.status().then((x) => setStore("lsp", x.data!))
          break
        }

        case "vcs.branch.updated": {
          setStore("vcs", { branch: event.properties.branch })
          break
        }
      }
    })

    const exit = useExit()
    const args = useArgs()

    async function bootstrap() {
      console.log("bootstrapping")
      if (sdk.penguin) {
        type PenguinSession = {
          id: string
          slug: string
          projectID: string
          directory: string
          title: string
          version: string
          time: {
            created: number
            updated: number
          }
        }
        const now = Date.now()
        const stamp = (value?: string) => {
          const time = value ? Date.parse(value) : NaN
          return Number.isFinite(time) ? time : now
        }
        const unwrap = (value: unknown) => {
          if (!value || typeof value !== "object") return value
          const record = value as Record<string, unknown>
          if (!("data" in record)) return value
          const keys = Object.keys(record)
          const wrapper = keys.every((key) => key === "data" || key === "meta")
          return wrapper ? record.data : value
        }
        const model = {
          id: "penguin-default",
          providerID: "penguin",
          api: {
            id: "penguin-web",
            url: sdk.url,
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
        const provider = {
          id: "penguin",
          name: "Penguin",
          source: "custom" as const,
          env: [],
          options: {},
          models: {
            [model.id]: model,
          },
        }
        const directory = store.path.directory || sdk.directory || process.cwd()
        const sessionsUrl = iife(() => {
          const url = new URL("/session", sdk.url)
          url.searchParams.set("directory", directory)
          url.searchParams.set("limit", "50")
          return url
        })
        const [providersData, providerListData, configData, providerAuthData, sessionsData, roster] = await Promise.all([
          fetch(new URL("/config/providers", sdk.url))
            .then((res) => (res.ok ? res.json() : undefined))
            .catch(() => undefined),
          fetch(new URL("/provider", sdk.url))
            .then((res) => (res.ok ? res.json() : undefined))
            .catch(() => undefined),
          fetch(new URL("/config", sdk.url))
            .then((res) => (res.ok ? res.json() : undefined))
            .catch(() => undefined),
          fetch(new URL("/provider/auth", sdk.url))
            .then((res) => (res.ok ? res.json() : undefined))
            .catch(() => undefined),
          fetch(sessionsUrl)
            .then((res) => (res.ok ? res.json() : undefined))
            .then((data) => (Array.isArray(data) ? data : []))
            .catch(() => []),
          fetch(new URL("/api/v1/agents", sdk.url))
            .then((res) => (res.ok ? res.json() : undefined))
            .then((data) => (Array.isArray(data) ? data : []))
            .catch(() => []),
        ])
        const list = sessionsData
        const providersPayload = unwrap(providersData) as Record<string, unknown> | undefined
        const providerListPayload = unwrap(providerListData) as Record<string, unknown> | undefined
        const configPayload = unwrap(configData)
        const providerAuthPayload = unwrap(providerAuthData)

        const providers = Array.isArray(providersPayload?.providers) ? providersPayload.providers : [provider]
        const providerDefault =
          providersPayload && typeof providersPayload.default === "object" && providersPayload.default
            ? (providersPayload.default as Record<string, string>)
            : { [provider.id]: model.id }
        const providerNext =
          providerListPayload &&
          Array.isArray(providerListPayload.all) &&
          providerListPayload.default &&
          Array.isArray(providerListPayload.connected)
            ? (providerListPayload as ProviderListResponse)
            : {
                all: [
                  {
                    id: provider.id,
                    name: provider.name,
                    env: provider.env,
                    models: {
                      [model.id]: {
                        id: model.id,
                        name: model.name,
                        release_date: model.release_date,
                        attachment: model.capabilities.attachment,
                        reasoning: model.capabilities.reasoning,
                        temperature: model.capabilities.temperature,
                        tool_call: model.capabilities.toolcall,
                        limit: model.limit,
                        status: model.status,
                        options: {},
                      },
                    },
                  },
                ],
                default: { [provider.id]: model.id },
                connected: [provider.id],
              }
        const providerAuth =
          providerAuthPayload && typeof providerAuthPayload === "object"
            ? (providerAuthPayload as Record<string, ProviderAuthMethod[]>)
            : {}
        const config = configPayload && typeof configPayload === "object" ? configPayload : { share: "disabled" }
        const mapped: PenguinSession[] = list.map((item: { [key: string]: unknown }) => {
          const sid = typeof item.id === "string" ? item.id : crypto.randomUUID()
          const title = typeof item.title === "string" ? item.title : `Session ${sid.slice(-8)}`
          const time = item.time
          const created =
            typeof time === "object" && time && "created" in time && typeof time.created === "number"
              ? time.created
              : stamp(typeof item.created_at === "string" ? item.created_at : undefined)
          const updated =
            typeof time === "object" && time && "updated" in time && typeof time.updated === "number"
              ? time.updated
              : stamp(typeof item.last_active === "string" ? item.last_active : undefined)
          const directoryValue =
            typeof item.directory === "string" ? item.directory : directory
          const payload = {
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
          const sessionMode = typeof item.agent_mode === "string" ? item.agent_mode : undefined
          if (sessionMode) {
            ;(payload as Record<string, unknown>).agent_mode = sessionMode
          }
          return payload
        })
        const usage = list.reduce(
          (acc: Record<string, SessionUsage>, item: { [key: string]: unknown }) => {
            const sid = typeof item.id === "string" ? item.id : ""
            if (!sid) return acc
            const next = parseUsage(item)
            if (!next) return acc
            acc[sid] = next
            return acc
          },
          {} as Record<string, SessionUsage>,
        )
        const session: PenguinSession[] = mapped
        const baseAgent = {
          name: "penguin",
          mode: "primary" as const,
          permission: [],
          options: {},
        }
        const agent = roster
          .map((item: { [key: string]: unknown }) => {
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
        const command = [
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
        const status = Object.fromEntries(
          session.map((item: PenguinSession) => [item.id, { type: "idle" as const }]),
        )
        batch(() => {
          setStore("provider", reconcile(providers))
          setStore("provider_default", reconcile(providerDefault))
          setStore("provider_next", reconcile(providerNext))
          setStore("provider_auth", reconcile(providerAuth))
          setStore("agent", reconcile(agent.length ? agent : [baseAgent]))
          setStore("command", reconcile(command))
          setStore("config", reconcile(config))
          setStore("session", reconcile(session))
          setStore("session_usage", reconcile(usage))
          setStore("session_status", reconcile(status))
          setStore(
            "path",
            reconcile({ home: "", state: "", config: "", worktree: "", directory }),
          )
          setStore("status", "complete")
        })

        const systemUrl = (pathname: string) => {
          const url = new URL(pathname, sdk.url)
          url.searchParams.set("directory", directory)
          return url
        }

        await Promise.all([
          fetch(systemUrl("/lsp"))
            .then((res) => (res.ok ? res.json() : []))
            .catch(() => []),
          fetch(systemUrl("/formatter"))
            .then((res) => (res.ok ? res.json() : []))
            .catch(() => []),
          fetch(systemUrl("/vcs"))
            .then((res) => (res.ok ? res.json() : undefined))
            .catch(() => undefined),
          fetch(systemUrl("/path"))
            .then((res) => (res.ok ? res.json() : undefined))
            .catch(() => undefined),
        ]).then((result) => {
          const lsp = result[0]
          const formatter = result[1]
          const vcs = result[2]
          const path = result[3]
          batch(() => {
            setStore("lsp", reconcile(Array.isArray(lsp) ? lsp : []))
            setStore("formatter", reconcile(Array.isArray(formatter) ? formatter : []))
            if (vcs) setStore("vcs", reconcile(vcs))
            if (path) setStore("path", reconcile(path))
          })
        })
        return
      }
      const start = Date.now() - 30 * 24 * 60 * 60 * 1000
      const sessionListPromise = sdk.client.session
        .list({ start: start })
        .then((x) => (x.data ?? []).toSorted((a, b) => a.id.localeCompare(b.id)))

      // blocking - include session.list when continuing a session
      const providersPromise = sdk.client.config.providers({}, { throwOnError: true })
      const providerListPromise = sdk.client.provider.list({}, { throwOnError: true })
      const agentsPromise = sdk.client.app.agents({}, { throwOnError: true })
      const configPromise = sdk.client.config.get({}, { throwOnError: true })
      const blockingRequests: Promise<unknown>[] = [
        providersPromise,
        providerListPromise,
        agentsPromise,
        configPromise,
        ...(args.continue ? [sessionListPromise] : []),
      ]

      await Promise.all(blockingRequests)
        .then(() => {
          const providersResponse = providersPromise.then((x) => x.data!)
          const providerListResponse = providerListPromise.then((x) => x.data!)
          const agentsResponse = agentsPromise.then((x) => x.data ?? [])
          const configResponse = configPromise.then((x) => x.data!)
          const sessionListResponse = args.continue ? sessionListPromise : undefined

          return Promise.all([
            providersResponse,
            providerListResponse,
            agentsResponse,
            configResponse,
            ...(sessionListResponse ? [sessionListResponse] : []),
          ]).then((responses) => {
            const providers = responses[0]
            const providerList = responses[1]
            const agents = responses[2]
            const config = responses[3]
            const sessions = responses[4]

            batch(() => {
              setStore("provider", reconcile(providers.providers))
              setStore("provider_default", reconcile(providers.default))
              setStore("provider_next", reconcile(providerList))
              setStore("agent", reconcile(agents))
              setStore("config", reconcile(config))
              if (sessions !== undefined) setStore("session", reconcile(sessions))
            })
          })
        })
        .then(() => {
          if (store.status !== "complete") setStore("status", "partial")
          // non-blocking
          Promise.all([
            ...(args.continue ? [] : [sessionListPromise.then((sessions) => setStore("session", reconcile(sessions)))]),
            sdk.client.command.list().then((x) => setStore("command", reconcile(x.data ?? []))),
            sdk.client.lsp.status().then((x) => setStore("lsp", reconcile(x.data!))),
            sdk.client.mcp.status().then((x) => setStore("mcp", reconcile(x.data!))),
            sdk.client.experimental.resource.list().then((x) => setStore("mcp_resource", reconcile(x.data ?? {}))),
            sdk.client.formatter.status().then((x) => setStore("formatter", reconcile(x.data!))),
            sdk.client.session.status().then((x) => {
              setStore("session_status", reconcile(x.data!))
            }),
            sdk.client.provider.auth().then((x) => setStore("provider_auth", reconcile(x.data ?? {}))),
            sdk.client.vcs.get().then((x) => setStore("vcs", reconcile(x.data))),
            sdk.client.path.get().then((x) => setStore("path", reconcile(x.data!))),
          ]).then(() => {
            setStore("status", "complete")
          })
        })
        .catch(async (e) => {
          Log.Default.error("tui bootstrap failed", {
            error: e instanceof Error ? e.message : String(e),
            name: e instanceof Error ? e.name : undefined,
            stack: e instanceof Error ? e.stack : undefined,
          })
          await exit(e)
        })
    }

    onMount(() => {
      bootstrap()
    })

    const fullSyncedSessions = new Set<string>()
    const result = {
      data: store,
      set: setStore,
      get status() {
        return store.status
      },
      get ready() {
        return store.status !== "loading"
      },
        session: {
          get(sessionID: string) {
            if (sdk.penguin) {
              return store.session.find((item) => item.id === sessionID)
            }
            const match = Binary.search(store.session, sessionID, (s) => s.id)
            if (match.found) return store.session[match.index]
            return undefined
          },
        status(sessionID: string) {
          const session = result.session.get(sessionID)
          if (!session) return "idle"
          if (session.time.compacting) return "compacting"
          const live = store.session_status[sessionID]
          if (live?.type === "busy") return "working"
          if (live?.type === "idle") return "idle"
          const messages = store.message[sessionID] ?? []
          const last = messages.at(-1)
          if (!last) return "idle"
          if (last.role !== "assistant") return "idle"
          return last.time.completed ? "idle" : "working"
        },
        async sync(sessionID: string) {
          if (fullSyncedSessions.has(sessionID)) return
          const fallback = sdk.penguin ? store.session.find((item) => item.id === sessionID) : undefined
          const hydrated = await hydrateSessionSnapshot(sdk.client, sessionID, {
            fallbackSession: fallback,
          })
          setStore(
            produce((draft) => {
              if (sdk.penguin) {
                const index = draft.session.findIndex((item) => item.id === sessionID)
                if (index >= 0) draft.session[index] = hydrated.session
                if (index < 0) draft.session.push(hydrated.session)
              }
              if (!sdk.penguin) {
                const match = Binary.search(draft.session, sessionID, (s) => s.id)
                if (match.found) draft.session[match.index] = hydrated.session
                if (!match.found) draft.session.splice(match.index, 0, hydrated.session)
              }
              const usage = parseUsage(hydrated.session)
              if (usage) draft.session_usage[sessionID] = usage
              draft.todo[sessionID] = hydrated.todo
              draft.message[sessionID] = sdk.penguin
                ? mergeHydratedMessages(
                    draft.message[sessionID],
                    hydrated.messages,
                    draft.part,
                  )
                : hydrated.messages.map((x) => x.info)
              for (const message of hydrated.messages) {
                draft.part[message.info.id] = message.parts
              }
              draft.session_diff[sessionID] = hydrated.diff
            }),
          )
          fullSyncedSessions.add(sessionID)
        },
      },
      bootstrap,
    }
    return result
  },
})
