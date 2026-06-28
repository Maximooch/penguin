import { createStore } from "solid-js/store"
import { batch, createEffect, createMemo } from "solid-js"
import { useSync } from "@tui/context/sync"
import { useTheme } from "@tui/context/theme"
import { uniqueBy } from "remeda"
import path from "path"
import { Global } from "@/global"
import { iife } from "@/util/iife"
import { createSimpleContext } from "./helper"
import { useToast } from "../ui/toast"
import { Provider } from "@/provider/provider"
import { useArgs } from "./args"
import { useSDK } from "./sdk"
import { RGBA } from "@opentui/core"
import type { Agent } from "@opencode-ai/sdk/v2"
import { nextVariantSelection } from "./variant-cycle"
import { resolveCatalogModel } from "../util/model-selection"

export const { use: useLocal, provider: LocalProvider } = createSimpleContext({
  name: "Local",
  init: () => {
    const sync = useSync()
    const sdk = useSDK()
    const toast = useToast()

    function resolveModel(model: { providerID: string; modelID: string }) {
      return resolveCatalogModel(sync.data.provider, model)
    }

    function isModelValid(model: { providerID: string; modelID: string }) {
      return resolveModel(model) !== undefined
    }

    function getFirstValidModel(...modelFns: (() => { providerID: string; modelID: string } | undefined)[]) {
      for (const modelFn of modelFns) {
        const model = modelFn()
        if (!model) continue
        const resolved = resolveModel(model)
        if (resolved) return resolved
      }
    }

    const agent = iife(() => {
      const agents = createMemo(() => sync.data.agent.filter((x) => x.mode !== "subagent" && !x.hidden))
      const [agentStore, setAgentStore] = createStore<{
        current: string
      }>({
        current: "build",
      })
      createEffect(() => {
        const current = agents().find((x) => x.name === agentStore.current)
        if (current) return
        const first = agents()[0]
        if (first) setAgentStore("current", first.name)
      })
      const { theme } = useTheme()
      const colors = createMemo(() => [
        theme.secondary,
        theme.accent,
        theme.success,
        theme.warning,
        theme.primary,
        theme.error,
      ])
      return {
        list() {
          return agents()
        },
        current() {
          return (
            agents().find((x) => x.name === agentStore.current) ??
            agents()[0] ??
            ({ name: agentStore.current } as Agent)
          )
        },
        set(name: string) {
          if (!agents().some((x) => x.name === name))
            return toast.show({
              variant: "warning",
              message: `Agent not found: ${name}`,
              duration: 3000,
            })
          setAgentStore("current", name)
        },
        move(direction: 1 | -1) {
          if (!agents().length) return
          batch(() => {
            let next = agents().findIndex((x) => x.name === agentStore.current) + direction
            if (next < 0) next = agents().length - 1
            if (next >= agents().length) next = 0
            const value = agents()[next]
            setAgentStore("current", value.name)
          })
        },
        color(name: string) {
          const all = sync.data.agent
          const agent = all.find((x) => x.name === name)
          if (agent?.color) return RGBA.fromHex(agent.color)
          const index = all.findIndex((x) => x.name === name)
          if (index === -1) return colors()[0]
          return colors()[index % colors().length]
        },
      }
    })

    const model = iife(() => {
      const [modelStore, setModelStore] = createStore<{
        ready: boolean
        model: Record<
          string,
          {
            providerID: string
            modelID: string
          }
        >
        recent: {
          providerID: string
          modelID: string
        }[]
        favorite: {
          providerID: string
          modelID: string
        }[]
        variant: Record<string, string | undefined>
        fast?: boolean
      }>({
        ready: false,
        model: {},
        recent: [],
        favorite: [],
        variant: {},
      })

      const file = Bun.file(path.join(Global.Path.state, "model.json"))
      const state = {
        pending: false,
      }

      function save() {
        if (!modelStore.ready) {
          state.pending = true
          return
        }
        state.pending = false
        Bun.write(
          file,
          JSON.stringify({
            recent: modelStore.recent,
            favorite: modelStore.favorite,
            variant: modelStore.variant,
            fast: modelStore.fast,
          }),
        )
      }

      file
        .json()
        .then((x) => {
          if (Array.isArray(x.recent)) setModelStore("recent", x.recent)
          if (Array.isArray(x.favorite)) setModelStore("favorite", x.favorite)
          if (typeof x.variant === "object" && x.variant !== null) setModelStore("variant", x.variant)
          if (typeof x.fast === "boolean") setModelStore("fast", x.fast)
        })
        .catch(() => {})
        .finally(() => {
          setModelStore("ready", true)
          if (state.pending) save()
        })

      const args = useArgs()
      const sessionModel = createMemo(() => {
        const sessionID = sdk.sessionID
        const session = sessionID
          ? (sync.session.get(sessionID) as
              | {
                  providerID?: string
                  modelID?: string
                }
              | undefined)
          : undefined
        if (!session?.providerID || !session?.modelID) return undefined
        const candidate = {
          providerID: session.providerID,
          modelID: session.modelID,
        }
        return resolveModel(candidate)
      })
      const fallbackModel = createMemo(() => {
        if (args.model) {
          const { providerID, modelID } = Provider.parseModel(args.model)
          const resolved = resolveModel({ providerID, modelID })
          if (resolved) {
            return {
              providerID,
              modelID: resolved.modelID,
            }
          }
        }

        const activeSessionModel = sessionModel()
        if (activeSessionModel) {
          return activeSessionModel
        }

        if (sync.data.config.model) {
          const { providerID, modelID } = Provider.parseModel(sync.data.config.model)
          const resolved = resolveModel({ providerID, modelID })
          if (resolved) {
            return {
              providerID,
              modelID: resolved.modelID,
            }
          }
        }

        for (const item of modelStore.recent) {
          const resolved = resolveModel(item)
          if (resolved) {
            return resolved
          }
        }

        const provider = sync.data.provider[0]
        if (!provider) return undefined
        const defaultModel = sync.data.provider_default[provider.id]
        const firstModel = Object.values(provider.models)[0]
        const model = defaultModel ?? firstModel?.id
        if (!model) return undefined
        return {
          providerID: provider.id,
          modelID: model,
        }
      })

      const currentModel = createMemo(() => {
        const a = agent.current()
        return (
          getFirstValidModel(
            () => modelStore.model[a.name],
            () => a.model,
            fallbackModel,
          ) ?? undefined
        )
      })

      return {
        current: currentModel,
        get ready() {
          return modelStore.ready
        },
        recent() {
          return modelStore.recent
        },
        favorite() {
          return modelStore.favorite
        },
        parsed: createMemo(() => {
          const value = currentModel()
          if (!value) {
            return {
              provider: "Connect a provider",
              model: "No provider selected",
              reasoning: false,
            }
          }
          const provider = sync.data.provider.find((x) => x.id === value.providerID)
          const info = provider?.models[value.modelID]
          return {
            provider: provider?.name ?? value.providerID,
            model: info?.name ?? value.modelID,
            reasoning: info?.capabilities?.reasoning ?? false,
          }
        }),
        cycle(direction: 1 | -1) {
          const current = currentModel()
          if (!current) return
          const recent = modelStore.recent
          const index = recent.findIndex((x) => x.providerID === current.providerID && x.modelID === current.modelID)
          if (index === -1) return
          let next = index + direction
          if (next < 0) next = recent.length - 1
          if (next >= recent.length) next = 0
          const val = recent[next]
          if (!val) return
          setModelStore("model", agent.current().name, { ...val })
        },
        cycleFavorite(direction: 1 | -1) {
          const favorites = modelStore.favorite.map(resolveModel).filter((item) => item !== undefined)
          if (!favorites.length) {
            toast.show({
              variant: "info",
              message: "Add a favorite model to use this shortcut",
              duration: 3000,
            })
            return
          }
          const current = currentModel()
          let index = -1
          if (current) {
            index = favorites.findIndex((x) => x.providerID === current.providerID && x.modelID === current.modelID)
          }
          if (index === -1) {
            index = direction === 1 ? 0 : favorites.length - 1
          } else {
            index += direction
            if (index < 0) index = favorites.length - 1
            if (index >= favorites.length) index = 0
          }
          const next = favorites[index]
          if (!next) return
          setModelStore("model", agent.current().name, { ...next })
          const uniq = uniqueBy([next, ...modelStore.recent], (x) => `${x.providerID}/${x.modelID}`)
          if (uniq.length > 10) uniq.pop()
          setModelStore(
            "recent",
            uniq.map((x) => ({ providerID: x.providerID, modelID: x.modelID })),
          )
          save()
        },
        set(model: { providerID: string; modelID: string }, options?: { recent?: boolean; silentInvalid?: boolean }) {
          batch(() => {
            const resolved = resolveModel(model)
            if (!resolved) {
              if (!options?.silentInvalid) {
                toast.show({
                  message: `Model ${model.providerID}/${model.modelID} is not valid`,
                  variant: "warning",
                  duration: 3000,
                })
              }
              return
            }
            setModelStore("model", agent.current().name, resolved)
            if (options?.recent) {
              const uniq = uniqueBy([resolved, ...modelStore.recent], (x) => `${x.providerID}/${x.modelID}`)
              if (uniq.length > 10) uniq.pop()
              setModelStore(
                "recent",
                uniq.map((x) => ({ providerID: x.providerID, modelID: x.modelID })),
              )
              save()
            }
          })
        },
        toggleFavorite(model: { providerID: string; modelID: string }) {
          batch(() => {
            const resolved = resolveModel(model)
            if (!resolved) {
              toast.show({
                message: `Model ${model.providerID}/${model.modelID} is not valid`,
                variant: "warning",
                duration: 3000,
              })
              return
            }
            const exists = modelStore.favorite.some(
              (x) => x.providerID === resolved.providerID && x.modelID === resolved.modelID,
            )
            const next = exists
              ? modelStore.favorite.filter(
                  (x) => x.providerID !== resolved.providerID || x.modelID !== resolved.modelID,
                )
              : [resolved, ...modelStore.favorite]
            setModelStore(
              "favorite",
              next.map((x) => ({ providerID: x.providerID, modelID: x.modelID })),
            )
            save()
          })
        },
        variant: {
          current() {
            const m = currentModel()
            if (!m) return undefined
            const key = `${m.providerID}/${m.modelID}`
            return modelStore.variant[key]
          },
          list() {
            const m = currentModel()
            if (!m) return []
            const provider = sync.data.provider.find((x) => x.id === m.providerID)
            const info = provider?.models[m.modelID]
            if (!info?.variants) return []
            return Object.keys(info.variants)
          },
          set(value: string | undefined) {
            const m = currentModel()
            if (!m) return
            const key = `${m.providerID}/${m.modelID}`
            setModelStore("variant", key, value)
            save()
          },
          cycle() {
            const result = nextVariantSelection(this.list(), this.current())
            if (result.type === "unavailable") {
              toast.show({
                title: "No variants available",
                message: "The current model does not support any variants.",
                variant: "info",
              })
              return
            }
            this.set(result.variant)
          },
        },
        fast: {
          override() {
            return modelStore.fast
          },
          enabled() {
            const config = sync.data.config as { service_tier?: string }
            return modelStore.fast ?? config.service_tier?.toLowerCase() === "priority"
          },
          set(value: boolean | undefined) {
            setModelStore("fast", value)
            save()
          },
          toggle() {
            this.set(!this.enabled())
          },
          serviceTier() {
            if (modelStore.fast === undefined) return undefined
            return modelStore.fast ? "priority" : "default"
          },
        },
      }
    })

    const mcp = {
      isEnabled(name: string) {
        const status = sync.data.mcp[name]
        return status?.status === "connected"
      },
      async toggle(name: string) {
        const status = sync.data.mcp[name]
        if (status?.status === "connected") {
          // Disable: disconnect the MCP
          await sdk.client.mcp.disconnect({ name })
        } else {
          // Enable/Retry: connect the MCP (handles disabled, failed, and other states)
          await sdk.client.mcp.connect({ name })
        }
      },
    }

    // Automatically update model when agent changes
    createEffect(() => {
      const value = agent.current()
      if (value.model) {
        const configuredModel = `${value.model.providerID}/${value.model.modelID}`
        const resolved = resolveModel(value.model)
        if (resolved)
          model.set(
            {
              providerID: resolved.providerID,
              modelID: resolved.modelID,
            },
            { silentInvalid: true },
          )
        else
          toast.show({
            variant: "warning",
            message: `Agent ${value.name}'s configured model ${configuredModel} is not valid`,
            duration: 3000,
          })
      }
    })

    const result = {
      model,
      agent,
      mcp,
    }
    return result
  },
})
