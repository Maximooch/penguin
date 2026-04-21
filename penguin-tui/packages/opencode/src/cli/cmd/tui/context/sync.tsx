import type {
  Message,
  Agent,
  Provider,
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
import { createStore, produce, reconcile } from "solid-js/store"
import { useSDK } from "@tui/context/sdk"
import { Binary } from "@opencode-ai/util/binary"
import { createSimpleContext } from "./helper"
import type { Snapshot } from "@/snapshot"
import { useExit } from "./exit"
import { useArgs } from "./args"
import { useRoute } from "./route"
import { batch, onMount } from "solid-js"
import { Log } from "@/util/log"
import type { Path } from "@opencode-ai/sdk"
import {
  hydrateSessionSnapshot,
  mergeHydratedMessages,
  upsertPenguinMessage,
} from "./session-hydration"
import { expandSessionSearchResults, removeSessionRecord, upsertSessionRecord } from "../util/session-family"
import {
  bootstrapPenguinState,
  fetchPenguinSessionUsage,
  getPenguinEventDirectory,
  getPenguinEventSessionID,
  normalizePenguinDirectory,
  parsePenguinSessionUsage,
  shouldProcessPenguinEvent,
  type PenguinSession,
  type SessionUsage,
} from "./penguin-sync"

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
      session: PenguinSession[]
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
    const route = useRoute()
    const fullSyncedSessions = new Set<string>()

    const sessionIndex = (sessionID: string) => store.session.findIndex((item) => item.id === sessionID)

    const upsertSession = (session: Session) => {
      setStore("session", reconcile(upsertSessionRecord(store.session, session)))
    }

    const removeSession = (sessionID: string) => {
      if (sessionIndex(sessionID) === -1) return
      setStore("session", reconcile(removeSessionRecord(store.session, sessionID)))
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

    const appDirectory = () => normalizePenguinDirectory(resolveDirectory())

    const sessionDirectory = (sessionID?: string) => {
      if (!sessionID) return undefined
      const session = store.session.find((item) => item.id === sessionID)
      return normalizePenguinDirectory(session?.directory)
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
      fetchPenguinSessionUsage({
        fetch: sdk.fetch,
        url: sdk.url,
        sessionID,
      })
        .then((usage) => {
          if (!usage) return
          setStore("session_usage", sessionID, reconcile(usage))
        })
        .catch(() => undefined)
        .finally(() => {
          usageRefreshInFlight.delete(sessionID)
        })
    }

    const syncSessionSnapshot = async (sessionID: string, force = false) => {
      if (!force && fullSyncedSessions.has(sessionID)) return

      const fallback = sdk.penguin ? store.session.find((item) => item.id === sessionID) : undefined
      const hydrated = await hydrateSessionSnapshot(sdk.client, sessionID, {
        fallbackSession: fallback,
      })
      setStore(
        produce((draft) => {
          if (sdk.penguin) {
            draft.session = upsertSessionRecord(draft.session, hydrated.session)
          }
          if (!sdk.penguin) {
            const match = Binary.search(draft.session, sessionID, (s) => s.id)
            if (match.found) draft.session[match.index] = hydrated.session
            if (!match.found) draft.session.splice(match.index, 0, hydrated.session)
          }
          const usage = parsePenguinSessionUsage(hydrated.session)
          if (usage) draft.session_usage[sessionID] = usage
          draft.todo[sessionID] = hydrated.todo
          draft.message[sessionID] = sdk.penguin
            ? mergeHydratedMessages(draft.message[sessionID], hydrated.messages, draft.part)
            : hydrated.messages.map((x) => x.info)
          for (const message of hydrated.messages) {
            draft.part[message.info.id] = message.parts
          }
          draft.session_diff[sessionID] = hydrated.diff
        }),
      )
      fullSyncedSessions.add(sessionID)
    }

    sdk.event.listen((e) => {
      const event = e.details
      if (sdk.penguin) {
        const activeSessionID = route.data.type === "session" ? route.data.sessionID : undefined
        if (
          !shouldProcessPenguinEvent({
            event,
            activeSessionID,
            appDirectory: appDirectory(),
            sessionDirectory,
          })
        )
          return
      }
      switch (event.type) {
        case "server.instance.disposed":
          fullSyncedSessions.clear()
          void bootstrap(true)
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
          const sessionID = event.properties.info.id
          removeSession(sessionID)
          fullSyncedSessions.delete(sessionID)
          setStore(
            produce((draft) => {
              const messages = draft.message[sessionID] ?? []
              for (const message of messages) {
                delete draft.part[message.id]
              }
              delete draft.message[sessionID]
              delete draft.todo[sessionID]
              delete draft.session_diff[sessionID]
              delete draft.session_status[sessionID]
              delete draft.session_usage[sessionID]
            }),
          )
          break
        }
        case "session.created":
        case "session.updated": {
          upsertSession(event.properties.info)
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
            setStore("message", normalized.sessionID, upsertPenguinMessage(messages, normalized))
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
          if (normalized.role === "assistant" && typeof normalized.time === "object" && !!normalized.time?.completed) {
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
            const scopedDirectory = getPenguinEventDirectory(event) ?? resolveDirectory(getPenguinEventSessionID(event))
            const normalizedScoped = normalizePenguinDirectory(scopedDirectory)
            const normalizedBase = appDirectory()
            if (!scopedDirectory) break
            if (normalizedScoped && normalizedBase && normalizedScoped !== normalizedBase) break
            const url = new URL("/lsp", sdk.url)
            url.searchParams.set("directory", scopedDirectory)
            sdk.fetch(url)
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

    async function bootstrap(refreshActive = false) {
      console.log("bootstrapping")
      if (sdk.penguin) {
        fullSyncedSessions.clear()
        const directory = store.path.directory || sdk.directory || process.cwd()
        const bootstrapState = await bootstrapPenguinState({
          fetch: sdk.fetch,
          url: sdk.url,
          directory,
        })
        batch(() => {
          setStore("provider", reconcile(bootstrapState.provider))
          setStore("provider_default", reconcile(bootstrapState.provider_default))
          setStore("provider_next", reconcile(bootstrapState.provider_next))
          setStore("provider_auth", reconcile(bootstrapState.provider_auth))
          setStore("agent", reconcile(bootstrapState.agent))
          setStore("command", reconcile(bootstrapState.command))
          setStore("config", reconcile(bootstrapState.config))
          setStore("session", reconcile(bootstrapState.session))
          setStore("session_usage", reconcile(bootstrapState.session_usage))
          setStore("session_status", reconcile(bootstrapState.session_status))
          setStore("lsp", reconcile(bootstrapState.lsp))
          setStore("formatter", reconcile(bootstrapState.formatter))
          if (bootstrapState.vcs) setStore("vcs", reconcile(bootstrapState.vcs))
          setStore("path", reconcile(bootstrapState.path))
          setStore("status", "complete")
        })
        const activeSessionID = route.data.type === "session" ? route.data.sessionID : undefined
        if (activeSessionID && (refreshActive || store.session.some((item) => item.id === activeSessionID))) {
          await syncSessionSnapshot(activeSessionID, true)
        }
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
      void bootstrap()
    })

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
          await syncSessionSnapshot(sessionID)
        },
      },
      bootstrap,
    }
    return result
  },
})
