import { BoxRenderable, TextareaRenderable, MouseEvent, PasteEvent, t, dim, fg } from "@opentui/core"
import { createEffect, createMemo, type JSX, onMount, createSignal, onCleanup, Show, Switch, Match } from "solid-js"
import "opentui-spinner/solid"
import { useLocal } from "@tui/context/local"
import { useTheme } from "@tui/context/theme"
import { EmptyBorder } from "@tui/component/border"
import { useSDK } from "@tui/context/sdk"
import { useRoute } from "@tui/context/route"
import { useSync } from "@tui/context/sync"
import { Identifier } from "@/id/id"
import { createStore, produce } from "solid-js/store"
import { useKeybind } from "@tui/context/keybind"
import { usePromptHistory, type PromptInfo } from "./history"
import { usePromptStash } from "./stash"
import { DialogStash } from "../dialog-stash"
import { type AutocompleteRef, Autocomplete } from "./autocomplete"
import { useCommandDialog } from "../dialog-command"
import { useRenderer } from "@opentui/solid"
import { Editor } from "@tui/util/editor"
import { useExit } from "../../context/exit"
import { Clipboard } from "../../util/clipboard"
import type { FilePart } from "@opencode-ai/sdk/v2"
import { TuiEvent } from "../../event"
import { iife } from "@/util/iife"
import { Locale } from "@/util/locale"
import { formatDuration } from "@/util/format"
import { createColors, createFrames } from "../../ui/spinner.ts"
import { useDialog } from "@tui/ui/dialog"
import { DialogProvider as DialogProviderConnect } from "../dialog-provider"
import { DialogSettings } from "../dialog-settings"
import { DialogAlert } from "../../ui/dialog-alert"
import { useToast } from "../../ui/toast"
import { useKV } from "../../context/kv"
import { useTextareaKeybindings } from "../textarea-keybindings"
import { exitSession } from "../../util/exit"
import { formatPenguinPromptFailure, recoverPenguinPromptFailure } from "./penguin-send"
import { parsePenguinLocalCommand } from "./penguin-local-command"
import {
  executePenguinHttpLocalCommand,
  isPenguinHttpLocalCommand,
  penguinHttpLocalCommandNeedsSession,
} from "./penguin-local-command-runtime"

export type PromptProps = {
  sessionID?: string
  visible?: boolean
  disabled?: boolean
  onSubmit?: () => void
  ref?: (ref: PromptRef) => void
  hint?: JSX.Element
  showPlaceholder?: boolean
}

export type PromptRef = {
  focused: boolean
  current: PromptInfo
  set(prompt: PromptInfo): void
  reset(): void
  blur(): void
  focus(): void
  submit(): void
}

const PLACEHOLDERS = ["Fix a TODO in the codebase", "What is the tech stack of this project?", "Fix broken tests"]

export function Prompt(props: PromptProps) {
  let input: TextareaRenderable
  let anchor: BoxRenderable
  let autocomplete: AutocompleteRef

  const keybind = useKeybind()
  const local = useLocal()
  const sdk = useSDK()
  const route = useRoute()
  const sync = useSync()
  const dialog = useDialog()
  const toast = useToast()
  const status = createMemo(() => sync.data.session_status?.[props.sessionID ?? ""] ?? { type: "idle" })
  const history = usePromptHistory()
  const stash = usePromptStash()
  const command = useCommandDialog()
  const renderer = useRenderer()
  const { theme, syntax } = useTheme()
  const kv = useKV()
  const model = createMemo(() => {
    const parsed = local.model.parsed()
    const current = local.model.current()
    if (!current) return parsed.model
    if (parsed.model === current.modelID) return parsed.model
    if (parsed.model.includes(current.modelID)) return parsed.model
    return `${parsed.model} (${current.modelID})`
  })
  const gen = iife(() => {
    const state = { ts: 0, inc: 0 }
    return {
      next(prefix: string) {
        const now = Date.now()
        const inc = now === state.ts ? state.inc + 1 : 0
        state.ts = now
        state.inc = inc
        const stamp = String(now).padStart(13, "0")
        const idx = String(inc).padStart(2, "0")
        return `${prefix}_${stamp}_${idx}`
      },
    }
  })

  function promptModelWarning() {
    toast.show({
      variant: "warning",
      message: "Connect a provider to send prompts",
      duration: 3000,
    })
    if (sync.data.provider.length === 0) {
      dialog.replace(() => <DialogProviderConnect />)
    }
  }

  const textareaKeybindings = useTextareaKeybindings()

  const fileStyleId = syntax().getStyleId("extmark.file")!
  const agentStyleId = syntax().getStyleId("extmark.agent")!
  const pasteStyleId = syntax().getStyleId("extmark.paste")!
  let promptPartTypeId = 0

  sdk.event.on(TuiEvent.PromptAppend.type, (evt) => {
    if (!input || input.isDestroyed) return
    input.insertText(evt.properties.text)
    setTimeout(() => {
      // setTimeout is a workaround and needs to be addressed properly
      if (!input || input.isDestroyed) return
      input.getLayoutNode().markDirty()
      input.gotoBufferEnd()
      renderer.requestRender()
    }, 0)
  })

  createEffect(() => {
    if (props.disabled) input.cursorColor = theme.backgroundElement
    if (!props.disabled) input.cursorColor = theme.text
  })

  const lastUserMessage = createMemo(() => {
    if (!props.sessionID) return undefined
    const messages = sync.data.message[props.sessionID]
    if (!messages) return undefined
    return messages.findLast((m) => m.role === "user")
  })

  const [store, setStore] = createStore<{
    prompt: PromptInfo
    mode: "normal" | "shell"
    extmarkToPartIndex: Map<number, number>
    interrupt: number
    pending: boolean
    pendingSeenBusy: boolean
    placeholder: number
  }>({
    placeholder: Math.floor(Math.random() * PLACEHOLDERS.length),
    prompt: {
      input: "",
      parts: [],
    },
    mode: "normal",
    extmarkToPartIndex: new Map(),
    interrupt: 0,
    pending: false,
    pendingSeenBusy: false,
  })
  const [agentMode, setAgentMode] = createSignal<"build" | "plan">("build")

  createEffect(() => {
    if (!props.sessionID) return
    const session = sync.session.get(props.sessionID) as { agent_mode?: string } | undefined
    const mode = session?.agent_mode
    if (mode === "plan" || mode === "build") setAgentMode(mode)
  })

  function persistAgentMode(sessionID: string, nextMode: "build" | "plan") {
    const modeUrl = new URL(`/session/${encodeURIComponent(sessionID)}`, sdk.url)
    sdk.fetch(modeUrl, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ agent_mode: nextMode }),
    }).catch(() => undefined)
  }

  function applyAgentMode(nextMode: "build" | "plan", options?: { notify?: boolean; sessionID?: string }) {
    setAgentMode(nextMode)
    const sessionID = options?.sessionID ?? props.sessionID ?? sdk.sessionID
    if (sessionID) persistAgentMode(sessionID, nextMode)
    if (options?.notify === false) return
    toast.show({ variant: "info", message: `Agent mode: ${nextMode}` })
  }

  function cycleAgentMode() {
    const nextMode = agentMode() === "build" ? "plan" : "build"
    applyAgentMode(nextMode)
  }

  const busy = createMemo(() => status().type !== "idle" || (sdk.penguin && store.pending))

  createEffect(() => {
    if (!sdk.penguin) return
    if (!store.pending) return
    if (status().type !== "idle") {
      if (!store.pendingSeenBusy) setStore("pendingSeenBusy", true)
      return
    }
    if (!store.pendingSeenBusy) return
    setStore("pending", false)
    setStore("pendingSeenBusy", false)
  })

  // Initialize agent/model/variant from session info first, then last user message fallback.
  let syncedSessionID: string | undefined
  createEffect(() => {
    const sessionID = props.sessionID
    const msg = lastUserMessage()
    const session = sessionID
      ? (sync.session.get(sessionID) as {
          agent_id?: string
          providerID?: string
          modelID?: string
          variant?: string
        } | undefined)
      : undefined

    if (sessionID !== syncedSessionID) {
      if (!sessionID) return

      syncedSessionID = sessionID

      const sessionAgent = session?.agent_id
      const messageAgent = msg?.agent
      const nextAgent = typeof sessionAgent === "string" && sessionAgent ? sessionAgent : messageAgent

      // Only set agent if it's a primary agent (not a subagent)
      const isPrimaryAgent = nextAgent ? local.agent.list().some((x) => x.name === nextAgent) : false
      if (nextAgent && isPrimaryAgent) {
        local.agent.set(nextAgent)
      }

      const sessionModel =
        session?.providerID && session?.modelID
          ? { providerID: session.providerID, modelID: session.modelID }
          : undefined
      const messageModel = msg?.model
      const nextModel = sessionModel ?? messageModel
      if (nextModel) {
        local.model.set(nextModel)
      }

      const nextVariant = session?.variant ?? msg?.variant
      if (typeof nextVariant === "string") {
        local.model.variant.set(nextVariant)
      } else if (nextModel) {
        local.model.variant.set(undefined)
      }
    }
  })

  command.register(() => {
    const prefillPrompt = (text: string) => {
      input.extmarks.clear()
      input.setText(text)
      setStore("prompt", { input: text, parts: [] })
      setStore("extmarkToPartIndex", new Map())
      input.gotoBufferEnd()
      input.focus()
      input.getLayoutNode().markDirty()
      renderer.requestRender()
    }

    return [
      {
        title: "Clear prompt",
        value: "prompt.clear",
        category: "Prompt",
        hidden: true,
        onSelect: (dialog) => {
          input.extmarks.clear()
          input.clear()
          dialog.clear()
        },
      },
      {
        title: "Submit prompt",
        value: "prompt.submit",
        keybind: "input_submit",
        category: "Prompt",
        hidden: true,
        onSelect: (dialog) => {
          if (!input.focused) return
          submit()
          dialog.clear()
        },
      },
      {
        title: "Cycle agent mode",
        value: "prompt.agent_mode.cycle",
        keybind: "agent_cycle",
        category: "Agent",
        hidden: true,
        enabled: sdk.penguin && store.mode === "normal",
        onSelect: () => {
          cycleAgentMode()
        },
      },
      {
        title: "Cycle agent mode reverse",
        value: "prompt.agent_mode.cycle.reverse",
        keybind: "agent_cycle_reverse",
        category: "Agent",
        hidden: true,
        enabled: sdk.penguin && store.mode === "normal",
        onSelect: () => {
          cycleAgentMode()
        },
      },
      {
        title: "Create project",
        description: "Prefill a project create command",
        value: "project.create.prefill",
        category: "Project",
        suggested: sdk.penguin,
        enabled: sdk.penguin,
        slash: {
          name: "project-create",
          aliases: ["project create"],
        },
        onSelect: (dialog) => {
          prefillPrompt('/project create "Project Name" --description "Project description"')
          dialog.clear()
        },
      },
      {
        title: "Initialize project from Blueprint",
        description: "Prefill a project init command for Penguin bootstrap workflows",
        value: "project.init.prefill",
        category: "Project",
        suggested: sdk.penguin,
        enabled: sdk.penguin,
        slash: {
          name: "project-init",
          aliases: ["project init"],
        },
        onSelect: (dialog) => {
          prefillPrompt('/project init "Project Name" --blueprint ./blueprint.md')
          dialog.clear()
        },
      },
      {
        title: "List projects",
        description: "Prefill a project list command",
        value: "project.list.prefill",
        category: "Project",
        suggested: sdk.penguin,
        enabled: sdk.penguin,
        slash: {
          name: "project-list",
          aliases: ["project list"],
        },
        onSelect: (dialog) => {
          prefillPrompt('/project list')
          dialog.clear()
        },
      },
      {
        title: "Show project",
        description: "Prefill a project show command",
        value: "project.show.prefill",
        category: "Project",
        suggested: sdk.penguin,
        enabled: sdk.penguin,
        slash: {
          name: "project-show",
          aliases: ["project show", "project get"],
        },
        onSelect: (dialog) => {
          prefillPrompt('/project show "Project ID"')
          dialog.clear()
        },
      },
      {
        title: "Start project execution",
        description: "Prefill a project start command for continuous project execution",
        value: "project.start.prefill",
        category: "Project",
        suggested: sdk.penguin,
        enabled: sdk.penguin,
        slash: {
          name: "project-start",
          aliases: ["project start"],
        },
        onSelect: (dialog) => {
          prefillPrompt('/project start "Project Name"')
          dialog.clear()
        },
      },
      {
        title: "Delete project",
        description: "Prefill a project delete command",
        value: "project.delete.prefill",
        category: "Project",
        suggested: sdk.penguin,
        enabled: sdk.penguin,
        slash: {
          name: "project-delete",
          aliases: ["project delete"],
        },
        onSelect: (dialog) => {
          prefillPrompt('/project delete "Project ID"')
          dialog.clear()
        },
      },
      {
        title: "Create task",
        description: "Prefill a task create command",
        value: "task.create.prefill",
        category: "Task",
        suggested: sdk.penguin,
        enabled: sdk.penguin,
        slash: {
          name: "task-create",
          aliases: ["task create"],
        },
        onSelect: (dialog) => {
          prefillPrompt('/task create "Project ID" "Task title"')
          dialog.clear()
        },
      },
      {
        title: "List tasks",
        description: "Prefill a task list command",
        value: "task.list.prefill",
        category: "Task",
        suggested: sdk.penguin,
        enabled: sdk.penguin,
        slash: {
          name: "task-list",
          aliases: ["task list"],
        },
        onSelect: (dialog) => {
          prefillPrompt('/task list')
          dialog.clear()
        },
      },
      {
        title: "Show task",
        description: "Prefill a task show command",
        value: "task.show.prefill",
        category: "Task",
        suggested: sdk.penguin,
        enabled: sdk.penguin,
        slash: {
          name: "task-show",
          aliases: ["task show", "task get"],
        },
        onSelect: (dialog) => {
          prefillPrompt('/task show "Task ID"')
          dialog.clear()
        },
      },
      {
        title: "Start task",
        description: "Prefill a task start command",
        value: "task.start.prefill",
        category: "Task",
        suggested: sdk.penguin,
        enabled: sdk.penguin,
        slash: {
          name: "task-start",
          aliases: ["task start"],
        },
        onSelect: (dialog) => {
          prefillPrompt('/task start "Task ID"')
          dialog.clear()
        },
      },
      {
        title: "Complete task",
        description: "Prefill a task complete command",
        value: "task.complete.prefill",
        category: "Task",
        suggested: sdk.penguin,
        enabled: sdk.penguin,
        slash: {
          name: "task-complete",
          aliases: ["task complete"],
        },
        onSelect: (dialog) => {
          prefillPrompt('/task complete "Task ID"')
          dialog.clear()
        },
      },
      {
        title: "Execute task",
        description: "Prefill a task execute command",
        value: "task.execute.prefill",
        category: "Task",
        suggested: sdk.penguin,
        enabled: sdk.penguin,
        slash: {
          name: "task-execute",
          aliases: ["task execute"],
        },
        onSelect: (dialog) => {
          prefillPrompt('/task execute "Task ID"')
          dialog.clear()
        },
      },
      {
        title: "Delete task",
        description: "Prefill a task delete command",
        value: "task.delete.prefill",
        category: "Task",
        suggested: sdk.penguin,
        enabled: sdk.penguin,
        slash: {
          name: "task-delete",
          aliases: ["task delete"],
        },
        onSelect: (dialog) => {
          prefillPrompt('/task delete "Task ID"')
          dialog.clear()
        },
      },
      {
        title: "Resume task clarification",
        description: "Prefill a task clarification resume command",
        value: "task.resume.prefill",
        category: "Task",
        suggested: sdk.penguin,
        enabled: sdk.penguin,
        slash: {
          name: "task-resume",
          aliases: ["task resume", "task clarification resume"],
        },
        onSelect: (dialog) => {
          prefillPrompt('/task resume "Task ID" "Clarification answer"')
          dialog.clear()
        },
      },
      {
        title: "Paste",
        value: "prompt.paste",
        keybind: "input_paste",
        category: "Prompt",
        hidden: true,
        onSelect: async () => {
          const content = await Clipboard.read()
          if (content?.mime.startsWith("image/")) {
            await pasteImage({
              filename: "clipboard",
              mime: content.mime,
              content: content.data,
            })
          }
        },
      },
      {
        title: "Interrupt session",
        value: "session.interrupt",
        keybind: "session_interrupt",
        category: "Session",
        hidden: true,
        enabled: sdk.penguin ? !!props.sessionID && (store.pending || status().type !== "idle") : status().type !== "idle",
        onSelect: (dialog) => {
          if (autocomplete.visible) return
          if (!input.focused && !sdk.penguin) return
          // TODO: this should be its own command
          if (store.mode === "shell") {
            setStore("mode", "normal")
            return
          }
          if (!props.sessionID) return

          if (sdk.penguin) {
            sdk.client.session.abort({
              sessionID: props.sessionID,
            })
            setStore("pending", false)
            setStore("pendingSeenBusy", false)
            setStore("interrupt", 0)
            dialog.clear()
            return
          }

          setStore("interrupt", store.interrupt + 1)

          setTimeout(() => {
            setStore("interrupt", 0)
          }, 5000)

          if (store.interrupt >= 2) {
            sdk.client.session.abort({
              sessionID: props.sessionID,
            })
            setStore("interrupt", 0)
          }
          dialog.clear()
        },
      },
      {
        title: "Open editor",
        category: "Session",
        keybind: "editor_open",
        value: "prompt.editor",
        slash: {
          name: "editor",
        },
        onSelect: async (dialog) => {
          dialog.clear()

          // replace summarized text parts with the actual text
          const text = store.prompt.parts
            .filter((p) => p.type === "text")
            .reduce((acc, p) => {
              if (!p.source) return acc
              return acc.replace(p.source.text.value, p.text)
            }, store.prompt.input)

          const nonTextParts = store.prompt.parts.filter((p) => p.type !== "text")

          const value = text
          const content = await Editor.open({ value, renderer })
          if (!content) return

          input.setText(content)

          // Update positions for nonTextParts based on their location in new content
          // Filter out parts whose virtual text was deleted
          // this handles a case where the user edits the text in the editor
          // such that the virtual text moves around or is deleted
          const updatedNonTextParts = nonTextParts
            .map((part) => {
              let virtualText = ""
              if (part.type === "file" && part.source?.text) {
                virtualText = part.source.text.value
              } else if (part.type === "agent" && part.source) {
                virtualText = part.source.value
              }

              if (!virtualText) return part

              const newStart = content.indexOf(virtualText)
              // if the virtual text is deleted, remove the part
              if (newStart === -1) return null

              const newEnd = newStart + virtualText.length

              if (part.type === "file" && part.source?.text) {
                return {
                  ...part,
                  source: {
                    ...part.source,
                    text: {
                      ...part.source.text,
                      start: newStart,
                      end: newEnd,
                    },
                  },
                }
              }

              if (part.type === "agent" && part.source) {
                return {
                  ...part,
                  source: {
                    ...part.source,
                    start: newStart,
                    end: newEnd,
                  },
                }
              }

              return part
            })
            .filter((part) => part !== null)

          setStore("prompt", {
            input: content,
            // keep only the non-text parts because the text parts were
            // already expanded inline
            parts: updatedNonTextParts,
          })
          restoreExtmarksFromParts(updatedNonTextParts)
          input.cursorOffset = Bun.stringWidth(content)
        },
      },
    ]
  })

  const ref: PromptRef = {
    get focused() {
      return input.focused
    },
    get current() {
      return store.prompt
    },
    focus() {
      input.focus()
    },
    blur() {
      input.blur()
    },
    set(prompt) {
      input.setText(prompt.input)
      setStore("prompt", prompt)
      restoreExtmarksFromParts(prompt.parts)
      input.gotoBufferEnd()
    },
    reset() {
      input.clear()
      input.extmarks.clear()
      setStore("prompt", {
        input: "",
        parts: [],
      })
      setStore("extmarkToPartIndex", new Map())
    },
    submit() {
      submit()
    },
  }

  createEffect(() => {
    if (props.visible !== false) input?.focus()
    if (props.visible === false) input?.blur()
  })

  function restoreExtmarksFromParts(parts: PromptInfo["parts"]) {
    input.extmarks.clear()
    setStore("extmarkToPartIndex", new Map())

    parts.forEach((part, partIndex) => {
      let start = 0
      let end = 0
      let virtualText = ""
      let styleId: number | undefined

      if (part.type === "file" && part.source?.text) {
        start = part.source.text.start
        end = part.source.text.end
        virtualText = part.source.text.value
        styleId = fileStyleId
      } else if (part.type === "agent" && part.source) {
        start = part.source.start
        end = part.source.end
        virtualText = part.source.value
        styleId = agentStyleId
      } else if (part.type === "text" && part.source?.text) {
        start = part.source.text.start
        end = part.source.text.end
        virtualText = part.source.text.value
        styleId = pasteStyleId
      }

      if (virtualText) {
        const extmarkId = input.extmarks.create({
          start,
          end,
          virtual: true,
          styleId,
          typeId: promptPartTypeId,
        })
        setStore("extmarkToPartIndex", (map: Map<number, number>) => {
          const newMap = new Map(map)
          newMap.set(extmarkId, partIndex)
          return newMap
        })
      }
    })
  }

  function syncExtmarksWithPromptParts() {
    const allExtmarks = input.extmarks.getAllForTypeId(promptPartTypeId)
    setStore(
      produce((draft) => {
        const newMap = new Map<number, number>()
        const newParts: typeof draft.prompt.parts = []

        for (const extmark of allExtmarks) {
          const partIndex = draft.extmarkToPartIndex.get(extmark.id)
          if (partIndex !== undefined) {
            const part = draft.prompt.parts[partIndex]
            if (part) {
              if (part.type === "agent" && part.source) {
                part.source.start = extmark.start
                part.source.end = extmark.end
              } else if (part.type === "file" && part.source?.text) {
                part.source.text.start = extmark.start
                part.source.text.end = extmark.end
              } else if (part.type === "text" && part.source?.text) {
                part.source.text.start = extmark.start
                part.source.text.end = extmark.end
              }
              newMap.set(extmark.id, newParts.length)
              newParts.push(part)
            }
          }
        }

        draft.extmarkToPartIndex = newMap
        draft.prompt.parts = newParts
      }),
    )
  }

  command.register(() => [
    {
      title: "Stash prompt",
      value: "prompt.stash",
      category: "Prompt",
      enabled: !!store.prompt.input,
      onSelect: (dialog) => {
        if (!store.prompt.input) return
        stash.push({
          input: store.prompt.input,
          parts: store.prompt.parts,
        })
        input.extmarks.clear()
        input.clear()
        setStore("prompt", { input: "", parts: [] })
        setStore("extmarkToPartIndex", new Map())
        dialog.clear()
      },
    },
    {
      title: "Stash pop",
      value: "prompt.stash.pop",
      category: "Prompt",
      enabled: stash.list().length > 0,
      onSelect: (dialog) => {
        const entry = stash.pop()
        if (entry) {
          input.setText(entry.input)
          setStore("prompt", { input: entry.input, parts: entry.parts })
          restoreExtmarksFromParts(entry.parts)
          input.gotoBufferEnd()
        }
        dialog.clear()
      },
    },
    {
      title: "Stash list",
      value: "prompt.stash.list",
      category: "Prompt",
      enabled: stash.list().length > 0,
      onSelect: (dialog) => {
        dialog.replace(() => (
          <DialogStash
            onSelect={(entry) => {
              input.setText(entry.input)
              setStore("prompt", { input: entry.input, parts: entry.parts })
              restoreExtmarksFromParts(entry.parts)
              input.gotoBufferEnd()
            }}
          />
        ))
      },
    },
  ])

  async function submit() {
    const resolveSessionID = (value: unknown): string | undefined => {
      if (typeof value === "string" && value.trim()) return value.trim()
      if (!value || typeof value !== "object") return undefined
      const record = value as Record<string, unknown>
      if (typeof record.id === "string" && record.id.trim()) return record.id.trim()
      return resolveSessionID(record.data)
    }

    if (props.disabled) return
    if (autocomplete?.visible) return
    if (!store.prompt.input) return
    const trimmed = store.prompt.input.trim()
    if (trimmed === "exit" || trimmed === "quit" || trimmed === ":q") {
      exit()
      return
    }
    const selectedModel = local.model.current()
    if (!selectedModel) {
      promptModelWarning()
      return
    }
    const currentMode = store.mode
    const variant = local.model.variant.current()
    const agent = local.agent.current()
    const getActiveDirectory = (activeSessionID?: string) => {
      return (
        (activeSessionID ? sync.session.get(activeSessionID)?.directory : undefined) ||
        sync.session.get(props.sessionID ?? sdk.sessionID ?? "")?.directory ||
        sync.data.path.directory ||
        sdk.directory ||
        process.cwd()
      )
    }
    const clearPromptState = (options?: { keepDialog?: boolean }) => {
      history.append({
        ...store.prompt,
        mode: currentMode,
      })
      if (!input.isDestroyed) {
        input.extmarks.clear()
      }
      setStore("prompt", {
        input: "",
        parts: [],
      })
      setStore("extmarkToPartIndex", new Map())
      if (!options?.keepDialog) {
        dialog.clear()
      }
      if (!input.isDestroyed) {
        input.clear()
        input.setText("")
        input.getLayoutNode().markDirty()
        renderer.requestRender()
      }
      queueMicrotask(() => {
        setStore("prompt", "input", "")
      })
    }
    const localCommand = sdk.penguin ? parsePenguinLocalCommand(store.prompt.input) : null
    const initialDirectory = getActiveDirectory(props.sessionID ?? sdk.sessionID)
    const ensureSessionID = async () => {
      return await iife(async () => {
        if (props.sessionID) return props.sessionID
        if (sdk.sessionID) return sdk.sessionID

        if (sdk.penguin) {
          const createUrl = new URL("/session", sdk.url)
          createUrl.searchParams.set("directory", initialDirectory)
          const created = await sdk.fetch(createUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              agent_mode: agentMode(),
              providerID: selectedModel.providerID,
              modelID: selectedModel.modelID,
              variant,
            }),
          }).then(async (res) => {
            if (!res.ok) {
              const details = await res.text().catch(() => "")
              throw new Error(
                details
                  ? `Session create failed (${res.status}): ${details}`
                  : `Session create failed (${res.status})`,
              )
            }
            return res.json().catch(() => undefined)
          })
          const createdID = resolveSessionID(created)
          if (createdID) return createdID
          const details =
            created && typeof created === "object"
              ? `response keys: ${Object.keys(created as Record<string, unknown>).join(",") || "none"}`
              : `response type: ${typeof created}`
          throw new Error(`Session create returned empty id (${details})`)
        }

        return await sdk.client.session.create({}).then((result) => {
          const id = resolveSessionID(result)
          if (id) return id
          throw new Error("Session create returned empty id")
        })
      }).catch((e) => {
        const msg = e instanceof Error ? e.message : String(e)
        toast.show({
          variant: "error",
          message: `Failed to start session: ${msg}`,
        })
        return undefined
      })
    }

    if (sdk.penguin && localCommand) {
      const commandNeedsSession = isPenguinHttpLocalCommand(localCommand) && penguinHttpLocalCommandNeedsSession(localCommand)
      const commandSessionID = commandNeedsSession ? await ensureSessionID() : props.sessionID ?? sdk.sessionID
      const keepDialog = localCommand.kind === "config" || localCommand.kind === "settings"

      if (commandNeedsSession && !commandSessionID) return

      try {
        if (localCommand.kind === "config" || localCommand.kind === "settings") {
          dialog.replace(() => <DialogSettings directory={initialDirectory} sessionID={commandSessionID} />)
        } else if (localCommand.kind === "tool_details") {
          const next = !kv.get("tool_details_visibility", true)
          kv.set("tool_details_visibility", next)
          toast.show({ variant: "success", message: `Tool details ${next ? "shown" : "hidden"}` })
        } else if (localCommand.kind === "thinking") {
          const next = !kv.get("thinking_visibility", true)
          kv.set("thinking_visibility", next)
          toast.show({ variant: "success", message: `Thinking ${next ? "shown" : "hidden"}` })
        } else if (isPenguinHttpLocalCommand(localCommand)) {
          const runCommand = () => executePenguinHttpLocalCommand({
            command: localCommand,
            fetch: sdk.fetch,
            baseUrl: sdk.url,
            directory: initialDirectory,
            sessionID: commandSessionID,
          })

          if (commandNeedsSession) {
            clearPromptState({ keepDialog })
            props.onSubmit?.()
            setStore("pending", true)
            setStore("pendingSeenBusy", false)
            if (!props.sessionID && commandSessionID) {
              setTimeout(() => {
                route.navigate({ type: "session", sessionID: commandSessionID })
              }, 0)
            }
            void runCommand()
              .then((result) => toast.show(result))
              .catch((error) => {
                toast.show({ variant: "error", message: error instanceof Error ? error.message : String(error) })
              })
              .finally(() => {
                setStore("pending", false)
                setStore("pendingSeenBusy", false)
              })
            return
          }

          const result = await runCommand()
          toast.show(result)
        }
      } catch (error) {
        toast.show({ variant: "error", message: error instanceof Error ? error.message : String(error) })
      }

      clearPromptState({ keepDialog })
      props.onSubmit?.()
      return
    }

    const sessionID = await ensureSessionID()
    if (!sessionID) return
    const shouldNavigate = sdk.penguin && !props.sessionID
    if (input.isDestroyed) return
    const directory =
      sync.session.get(sessionID)?.directory ||
      sync.session.get(props.sessionID ?? "")?.directory ||
      sync.data.path.directory ||
      sdk.directory ||
      process.cwd()
    const messageID = sdk.penguin ? gen.next("msg") : Identifier.ascending("message")
    let inputText = store.prompt.input

    // Expand pasted text inline before submitting
    const allExtmarks = input.extmarks.getAllForTypeId(promptPartTypeId)
    const sortedExtmarks = allExtmarks.sort((a: { start: number }, b: { start: number }) => b.start - a.start)

    for (const extmark of sortedExtmarks) {
      const partIndex = store.extmarkToPartIndex.get(extmark.id)
      if (partIndex !== undefined) {
        const part = store.prompt.parts[partIndex]
        if (!part) continue
        const before = inputText.slice(0, extmark.start)
        const after = inputText.slice(extmark.end)
        if (part.type === "text" && part.text) {
          inputText = before + part.text + after
          continue
        }
        const stripVirtualPart =
          sdk.penguin && part.type === "file" && typeof part.mime === "string" && part.mime.startsWith("image/")
        if (stripVirtualPart) {
          inputText = before + after
        }
      }
    }

    // Filter out text parts (pasted content) since they're now expanded inline
    const nonTextParts = store.prompt.parts.filter((part) => part.type !== "text")

    if (sdk.penguin) {
      const now = Date.now()
      const user = {
        id: messageID,
        sessionID,
        role: "user" as const,
        time: {
          created: now,
        },
        agent: agent.name,
        model: {
          providerID: selectedModel.providerID,
          modelID: selectedModel.modelID,
        },
      }
      const part = {
        id: sdk.penguin ? gen.next("part") : Identifier.ascending("part"),
        sessionID,
        messageID,
        type: "text" as const,
        text: inputText,
        time: {
          start: now,
          end: now,
        },
      }
      sdk.event.emit("message.updated", {
        type: "message.updated",
        properties: { info: user },
      })
      sdk.event.emit("message.part.updated", {
        type: "message.part.updated",
        properties: { part, delta: inputText },
      })
      sdk.event.emit("session.status", {
        type: "session.status",
        properties: {
          sessionID,
          status: { type: "busy" as const },
        },
      })
      history.append({
        ...store.prompt,
        mode: currentMode,
      })
      if (!input.isDestroyed) {
        input.extmarks.clear()
      }
      setStore("prompt", {
        input: "",
        parts: [],
      })
      setStore("extmarkToPartIndex", new Map())
      dialog.clear()
      if (!input.isDestroyed) {
        input.clear()
        input.setText("")
        input.getLayoutNode().markDirty()
        renderer.requestRender()
      }
      queueMicrotask(() => {
        setStore("prompt", "input", "")
      })
      props.onSubmit?.()
      if (shouldNavigate) {
        setTimeout(() => {
          route.navigate({
            type: "session",
            sessionID,
          })
        }, 0)
      }
      setStore("pending", true)
      setStore("pendingSeenBusy", false)
      const recover = () => {
        recoverPenguinPromptFailure({
          sessionID,
          clear: () => {
            setStore("pending", false)
            setStore("pendingSeenBusy", false)
          },
          emit: sdk.event.emit,
        })
      }
      const url = new URL("/api/v1/chat/message", sdk.url)
      sdk.fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          text: inputText,
          model: `${selectedModel.providerID}/${selectedModel.modelID}`,
          session_id: sessionID,
          agent_id: agent.name,
          agent_mode: agentMode(),
          directory,
          streaming: true,
          variant,
          client_message_id: messageID,
          parts: nonTextParts,
        }),
      })
        .then(async (res) => {
          if (res.ok) return
          const details = await res.text().catch(() => "")
          recover()
          toast.show({
            variant: "error",
            message: formatPenguinPromptFailure({
              status: res.status,
              details,
            }),
          })
        })
        .catch((err) => {
          recover()
          toast.show({
            variant: "error",
            message: formatPenguinPromptFailure({ error: err }),
          })
        })
      return
    }

    if (store.mode === "shell") {
      sdk.client.session.shell({
        sessionID,
        agent: agent.name,
        model: {
          providerID: selectedModel.providerID,
          modelID: selectedModel.modelID,
        },
        command: inputText,
      })
      setStore("mode", "normal")
    } else if (
      inputText.startsWith("/") &&
      iife(() => {
        const firstLine = inputText.split("\n")[0]
        const command = firstLine.split(" ")[0].slice(1)
        return sync.data.command.some((x) => x.name === command)
      })
    ) {
      // Parse command from first line, preserve multi-line content in arguments
      const firstLineEnd = inputText.indexOf("\n")
      const firstLine = firstLineEnd === -1 ? inputText : inputText.slice(0, firstLineEnd)
      const [command, ...firstLineArgs] = firstLine.split(" ")
      const restOfInput = firstLineEnd === -1 ? "" : inputText.slice(firstLineEnd + 1)
      const args = firstLineArgs.join(" ") + (restOfInput ? "\n" + restOfInput : "")

      sdk.client.session.command({
        sessionID,
        command: command.slice(1),
        arguments: args,
        agent: agent.name,
        model: `${selectedModel.providerID}/${selectedModel.modelID}`,
        messageID,
        variant,
        parts: nonTextParts
          .filter((x) => x.type === "file")
          .map((x) => ({
            id: Identifier.ascending("part"),
            ...x,
          })),
      })
    } else {
      sdk.client.session
        .prompt({
          sessionID,
          ...selectedModel,
          messageID,
          agent: agent.name,
          model: selectedModel,
          variant,
          parts: [
            {
              id: Identifier.ascending("part"),
              type: "text",
              text: inputText,
            },
            ...nonTextParts.map((x) => ({
              id: Identifier.ascending("part"),
              ...x,
            })),
          ],
        })
        .catch(() => {})
    }
    history.append({
      ...store.prompt,
      mode: currentMode,
    })
    input.extmarks.clear()
    setStore("prompt", {
      input: "",
      parts: [],
    })
    setStore("extmarkToPartIndex", new Map())
    props.onSubmit?.()

    // temporary hack to make sure the message is sent
    if (!props.sessionID)
      setTimeout(() => {
        route.navigate({
          type: "session",
          sessionID,
        })
      }, 50)
    input.clear()
  }
  const exit = useExit()

  function pasteText(text: string, virtualText: string) {
    const currentOffset = input.visualCursor.offset
    const extmarkStart = currentOffset
    const extmarkEnd = extmarkStart + virtualText.length

    input.insertText(virtualText + " ")

    const extmarkId = input.extmarks.create({
      start: extmarkStart,
      end: extmarkEnd,
      virtual: true,
      styleId: pasteStyleId,
      typeId: promptPartTypeId,
    })

    setStore(
      produce((draft) => {
        const partIndex = draft.prompt.parts.length
        draft.prompt.parts.push({
          type: "text" as const,
          text,
          source: {
            text: {
              start: extmarkStart,
              end: extmarkEnd,
              value: virtualText,
            },
          },
        })
        draft.extmarkToPartIndex.set(extmarkId, partIndex)
      }),
    )
  }

  async function pasteImage(file: { filename?: string; content: string; mime: string }) {
    const currentOffset = input.visualCursor.offset
    const extmarkStart = currentOffset
    const count = store.prompt.parts.filter((x) => x.type === "file").length
    const virtualText = `[Image ${count + 1}]`
    const extmarkEnd = extmarkStart + virtualText.length
    const textToInsert = virtualText + " "

    input.insertText(textToInsert)

    const extmarkId = input.extmarks.create({
      start: extmarkStart,
      end: extmarkEnd,
      virtual: true,
      styleId: pasteStyleId,
      typeId: promptPartTypeId,
    })

    const part: Omit<FilePart, "id" | "messageID" | "sessionID"> = {
      type: "file" as const,
      mime: file.mime,
      filename: file.filename,
      url: `data:${file.mime};base64,${file.content}`,
      source: {
        type: "file",
        path: file.filename ?? "",
        text: {
          start: extmarkStart,
          end: extmarkEnd,
          value: virtualText,
        },
      },
    }
    setStore(
      produce((draft) => {
        const partIndex = draft.prompt.parts.length
        draft.prompt.parts.push(part)
        draft.extmarkToPartIndex.set(extmarkId, partIndex)
      }),
    )
    return
  }

  const highlight = createMemo(() => {
    if (keybind.leader) return theme.border
    if (store.mode === "shell") return theme.primary
    return local.agent.color(local.agent.current().name)
  })

  const showVariant = createMemo(() => {
    const variants = local.model.variant.list()
    if (variants.length === 0) return false
    const current = local.model.variant.current()
    return !!current
  })

  const spinnerDef = createMemo(() => {
    const color = local.agent.color(local.agent.current().name)
    return {
      frames: createFrames({
        color,
        style: "blocks",
        inactiveFactor: 0.6,
        // enableFading: false,
        minAlpha: 0.3,
      }),
      color: createColors({
        color,
        style: "blocks",
        inactiveFactor: 0.6,
        // enableFading: false,
        minAlpha: 0.3,
      }),
    }
  })

  return (
    <>
      <Autocomplete
        sessionID={props.sessionID}
        ref={(r) => (autocomplete = r)}
        anchor={() => anchor}
        input={() => input}
        setPrompt={(cb) => {
          setStore("prompt", produce(cb))
        }}
        setExtmark={(partIndex, extmarkId) => {
          setStore("extmarkToPartIndex", (map: Map<number, number>) => {
            const newMap = new Map(map)
            newMap.set(extmarkId, partIndex)
            return newMap
          })
        }}
        value={store.prompt.input}
        fileStyleId={fileStyleId}
        agentStyleId={agentStyleId}
        promptPartTypeId={() => promptPartTypeId}
      />
      <box ref={(r) => (anchor = r)} visible={props.visible !== false}>
        <box
          border={["left"]}
          borderColor={highlight()}
          customBorderChars={{
            ...EmptyBorder,
            vertical: "┃",
            bottomLeft: "╹",
          }}
        >
          <box
            paddingLeft={2}
            paddingRight={2}
            paddingTop={1}
            flexShrink={0}
            backgroundColor={theme.backgroundElement}
            flexGrow={1}
          >
            <textarea
              placeholder={props.sessionID ? undefined : `Ask anything... "${PLACEHOLDERS[store.placeholder]}"`}
              textColor={keybind.leader ? theme.textMuted : theme.text}
              focusedTextColor={keybind.leader ? theme.textMuted : theme.text}
              minHeight={1}
              maxHeight={6}
              onContentChange={() => {
                const value = input.plainText
                setStore("prompt", "input", value)
                autocomplete.onInput(value)
                syncExtmarksWithPromptParts()
              }}
              keyBindings={textareaKeybindings()}
              onKeyDown={async (e) => {
                if (props.disabled) {
                  e.preventDefault()
                  return
                }
                // Handle clipboard paste (Ctrl+V) - check for images first on Windows
                // This is needed because Windows terminal doesn't properly send image data
                // through bracketed paste, so we need to intercept the keypress and
                // directly read from clipboard before the terminal handles it
                if (keybind.match("input_paste", e)) {
                  const content = await Clipboard.read()
                  if (content?.mime.startsWith("image/")) {
                    e.preventDefault()
                    await pasteImage({
                      filename: "clipboard",
                      mime: content.mime,
                      content: content.data,
                    })
                    return
                  }
                  // If no image, let the default paste behavior continue
                }
                if (keybind.match("input_clear", e) && store.prompt.input !== "") {
                  input.clear()
                  input.extmarks.clear()
                  setStore("prompt", {
                    input: "",
                    parts: [],
                  })
                  setStore("extmarkToPartIndex", new Map())
                  return
                }
                if (
                  sdk.penguin &&
                  props.sessionID &&
                  (keybind.match("session_interrupt", e) || e.name === "escape")
                ) {
                  const active = store.pending || status().type !== "idle"
                  if (active) {
                    sdk.client.session.abort({
                      sessionID: props.sessionID,
                    }).catch(() => {})
                    setStore("pending", false)
                    setStore("pendingSeenBusy", false)
                    setStore("interrupt", 0)
                    e.preventDefault()
                    return
                  }
                }
                if (keybind.match("app_exit", e)) {
                  if (store.prompt.input === "") {
                    await exitSession({
                      busy: store.pending || status().type !== "idle",
                      sessionID: props.sessionID,
                      dialog,
                      sdk,
                      sync,
                      exit,
                    })
                    // Don't preventDefault - let textarea potentially handle the event
                    e.preventDefault()
                    return
                  }
                }
                if (e.name === "!" && input.visualCursor.offset === 0) {
                  setStore("mode", "shell")
                  e.preventDefault()
                  return
                }
                if (store.mode === "shell") {
                  if ((e.name === "backspace" && input.visualCursor.offset === 0) || e.name === "escape") {
                    setStore("mode", "normal")
                    e.preventDefault()
                    return
                  }
                }
                if (store.mode === "normal") autocomplete.onKeyDown(e)
                if (!autocomplete.visible) {
                  if (
                    (keybind.match("history_previous", e) && input.cursorOffset === 0) ||
                    (keybind.match("history_next", e) && input.cursorOffset === input.plainText.length)
                  ) {
                    const direction = keybind.match("history_previous", e) ? -1 : 1
                    const item = history.move(direction, input.plainText)

                    if (item) {
                      input.setText(item.input)
                      setStore("prompt", item)
                      setStore("mode", item.mode ?? "normal")
                      restoreExtmarksFromParts(item.parts)
                      e.preventDefault()
                      if (direction === -1) input.cursorOffset = 0
                      if (direction === 1) input.cursorOffset = input.plainText.length
                    }
                    return
                  }

                  if (keybind.match("history_previous", e) && input.visualCursor.visualRow === 0) input.cursorOffset = 0
                  if (keybind.match("history_next", e) && input.visualCursor.visualRow === input.height - 1)
                    input.cursorOffset = input.plainText.length
                }
              }}
              onSubmit={submit}
              onPaste={async (event: PasteEvent) => {
                if (props.disabled) {
                  event.preventDefault()
                  return
                }

                // Normalize line endings at the boundary
                // Windows ConPTY/Terminal often sends CR-only newlines in bracketed paste
                // Replace CRLF first, then any remaining CR
                const normalizedText = event.text.replace(/\r\n/g, "\n").replace(/\r/g, "\n")
                const pastedContent = normalizedText.trim()
                if (!pastedContent) {
                  command.trigger("prompt.paste")
                  return
                }

                // trim ' from the beginning and end of the pasted content. just
                // ' and nothing else
                const filepath = pastedContent.replace(/^'+|'+$/g, "").replace(/\\ /g, " ")
                const matches = normalizedText.match(
                  /(?:\/|[A-Za-z]:\\)[^\n\r]*?\.(?:png|jpg|jpeg|gif|webp|bmp|svg)/gi,
                )
                const rawPaths = (matches ?? [])
                  .map((item) => item.replace(/^'+|'+$/g, "").trim())
                  .filter((item, index, all) => !!item && all.indexOf(item) === index)
                const paths = (matches ?? [])
                  .map((item) => item.replace(/^'+|'+$/g, "").replace(/\\ /g, " ").trim())
                  .filter((item, index, all) => !!item && all.indexOf(item) === index)
                const candidates = [filepath, ...rawPaths, ...paths]
                  .map((item) => item.replace(/^'+|'+$/g, "").replace(/\\ /g, " ").trim())
                  .filter((item, index, all) => !!item && all.indexOf(item) === index)

                const pathLike =
                  candidates.length > 1 ||
                  filepath.startsWith("/") ||
                  filepath.startsWith("./") ||
                  filepath.startsWith("../") ||
                  filepath.startsWith("~/") ||
                  filepath.startsWith("file://") ||
                  /^[A-Za-z]:[\\/]/.test(filepath)

                if (pathLike) {
                  // Prevent default paste immediately so local path text does not
                  // get inserted before we convert to [Image n].
                  event.preventDefault()
                }

                for (const entry of candidates) {
                  const local = entry.startsWith("file://")
                    ? iife(() => {
                        try {
                          return decodeURIComponent(new URL(entry).pathname)
                        } catch {
                          return entry.replace(/^file:\/\//, "")
                        }
                      })
                    : entry
                  const isUrl = /^(https?):\/\//.test(local)
                  if (isUrl) continue
                  try {
                    const file = Bun.file(local)
                    const exists = await file.exists().catch(() => false)
                    if (!exists) continue

                    // Handle SVG as raw text content, not as base64 image
                    if (file.type === "image/svg+xml") {
                      event.preventDefault()
                      const content = await file.text().catch(() => {})
                      if (content) {
                        pasteText(content, `[SVG: ${file.name ?? "image"}]`)
                        return
                      }
                    }
                    if (file.type.startsWith("image/")) {
                      event.preventDefault()
                      const content = await file
                        .arrayBuffer()
                        .then((buffer) => Buffer.from(buffer).toString("base64"))
                        .catch(() => {})
                      if (content) {
                        const remove = [entry, local, filepath, ...rawPaths, ...paths]
                          .filter((item, index, all) => !!item && all.indexOf(item) === index)
                          .flatMap((item) => [
                            item,
                            item.replace(/\\ /g, " "),
                            item.replace(/ /g, "\\ "),
                          ])
                          .filter((item, index, all) => !!item && all.indexOf(item) === index)
                        const cleaned = remove
                          .reduce((text, item) => text.split(item).join(" "), normalizedText)
                          .replace(/\s+/g, " ")
                          .trim()
                        if (cleaned) {
                          input.insertText(`${cleaned} `)
                        }
                        await pasteImage({
                          filename: file.name,
                          mime: file.type,
                          content,
                        })
                        return
                      }
                    }
                  } catch {}
                }

                if (pathLike) {
                  // No valid image detected from a path-like paste; preserve
                  // original pasted text behavior.
                  input.insertText(normalizedText)
                  return
                }

                const lineCount = (pastedContent.match(/\n/g)?.length ?? 0) + 1
                if (
                  (lineCount >= 3 || pastedContent.length > 150) &&
                  !sync.data.config.experimental?.disable_paste_summary
                ) {
                  event.preventDefault()
                  pasteText(pastedContent, `[Pasted ~${lineCount} lines]`)
                  return
                }

                // Force layout update and render for the pasted content
                setTimeout(() => {
                  // setTimeout is a workaround and needs to be addressed properly
                  if (!input || input.isDestroyed) return
                  input.getLayoutNode().markDirty()
                  renderer.requestRender()
                }, 0)
              }}
              ref={(r: TextareaRenderable) => {
                input = r
                if (promptPartTypeId === 0) {
                  promptPartTypeId = input.extmarks.registerType("prompt-part")
                }
                props.ref?.(ref)
                setTimeout(() => {
                  // setTimeout is a workaround and needs to be addressed properly
                  if (!input || input.isDestroyed) return
                  input.cursorColor = theme.text
                }, 0)
              }}
              onMouseDown={(r: MouseEvent) => r.target?.focus()}
              focusedBackgroundColor={theme.backgroundElement}
              cursorColor={theme.text}
              syntaxStyle={syntax()}
            />
            <box flexDirection="row" flexShrink={0} paddingTop={1} gap={1}>
              <text fg={highlight()}>
                {store.mode === "shell"
                  ? "Shell"
                  : sdk.penguin
                    ? Locale.titlecase(agentMode())
                    : Locale.titlecase(local.agent.current().name)}{" "}
              </text>
              <Show when={store.mode === "normal"}>
                <box flexDirection="row" gap={1}>
                  <text flexShrink={0} fg={keybind.leader ? theme.textMuted : theme.text}>
                    {model()}
                  </text>
                  <text fg={theme.textMuted}>{local.model.parsed().provider}</text>
                  <Show when={showVariant()}>
                    <text fg={theme.textMuted}>·</text>
                    <text>
                      <span style={{ fg: theme.warning, bold: true }}>{local.model.variant.current()}</span>
                    </text>
                  </Show>
                </box>
              </Show>
            </box>
          </box>
        </box>
        <box
          height={1}
          border={["left"]}
          borderColor={highlight()}
          customBorderChars={{
            ...EmptyBorder,
            vertical: theme.backgroundElement.a !== 0 ? "╹" : " ",
          }}
        >
          <box
            height={1}
            border={["bottom"]}
            borderColor={theme.backgroundElement}
            customBorderChars={
              theme.backgroundElement.a !== 0
                ? {
                    ...EmptyBorder,
                    horizontal: "▀",
                  }
                : {
                    ...EmptyBorder,
                    horizontal: " ",
                  }
            }
          />
        </box>
        <box flexDirection="row" justifyContent="space-between">
          <Show when={busy()} fallback={<text />}>
            <box
              flexDirection="row"
              gap={1}
              flexGrow={1}
              justifyContent={status().type === "retry" ? "space-between" : "flex-start"}
            >
              <box flexShrink={0} flexDirection="row" gap={1}>
                <box marginLeft={1}>
                  <Show when={kv.get("animations_enabled", true)} fallback={<text fg={theme.textMuted}>[⋯]</text>}>
                    <spinner color={spinnerDef().color} frames={spinnerDef().frames} interval={40} />
                  </Show>
                </box>
                <box flexDirection="row" gap={1} flexShrink={0}>
                  {(() => {
                    const retry = createMemo(() => {
                      const s = status()
                      if (s.type !== "retry") return
                      return s
                    })
                    const message = createMemo(() => {
                      const r = retry()
                      if (!r) return
                      if (r.message.includes("exceeded your current quota") && r.message.includes("gemini"))
                        return "gemini is way too hot right now"
                      if (r.message.length > 80) return r.message.slice(0, 80) + "..."
                      return r.message
                    })
                    const isTruncated = createMemo(() => {
                      const r = retry()
                      if (!r) return false
                      return r.message.length > 120
                    })
                    const [seconds, setSeconds] = createSignal(0)
                    onMount(() => {
                      const timer = setInterval(() => {
                        const next = retry()?.next
                        if (next) setSeconds(Math.round((next - Date.now()) / 1000))
                      }, 1000)

                      onCleanup(() => {
                        clearInterval(timer)
                      })
                    })
                    const handleMessageClick = () => {
                      const r = retry()
                      if (!r) return
                      if (isTruncated()) {
                        DialogAlert.show(dialog, "Retry Error", r.message)
                      }
                    }

                    const retryText = () => {
                      const r = retry()
                      if (!r) return ""
                      const baseMessage = message()
                      const truncatedHint = isTruncated() ? " (click to expand)" : ""
                      const duration = formatDuration(seconds())
                      const retryInfo = ` [retrying ${duration ? `in ${duration} ` : ""}attempt #${r.attempt}]`
                      return baseMessage + truncatedHint + retryInfo
                    }

                    return (
                      <Show when={retry()}>
                        <box onMouseUp={handleMessageClick}>
                          <text fg={theme.error}>{retryText()}</text>
                        </box>
                      </Show>
                    )
                  })()}
                </box>
              </box>
              <text fg={store.interrupt > 0 && !sdk.penguin ? theme.primary : theme.text}>
                esc{" "}
                <span style={{ fg: store.interrupt > 0 && !sdk.penguin ? theme.primary : theme.textMuted }}>
                  {sdk.penguin ? "interrupt" : store.interrupt > 0 ? "again to interrupt" : "interrupt"}
                </span>
              </text>
            </box>
          </Show>
          <Show when={status().type !== "retry"}>
            <box gap={2} flexDirection="row">
              <Switch>
                <Match when={store.mode === "normal"}>
                  <Show when={local.model.variant.list().length > 0}>
                    <text fg={theme.text}>
                      {keybind.print("variant_cycle")} <span style={{ fg: theme.textMuted }}>variants</span>
                    </text>
                  </Show>
                  <text fg={theme.text}>
                    {keybind.print("agent_cycle")} <span style={{ fg: theme.textMuted }}>{sdk.penguin ? "mode" : "agents"}</span>
                  </text>
                  <text fg={theme.text}>
                    {keybind.print("command_list")} <span style={{ fg: theme.textMuted }}>commands</span>
                  </text>
                  <text fg={theme.text}>
                    {keybind.print("app_exit")} <span style={{ fg: theme.textMuted }}>exit</span>
                  </text>
                </Match>
                <Match when={store.mode === "shell"}>
                  <text fg={theme.text}>
                    esc <span style={{ fg: theme.textMuted }}>exit shell mode</span>
                  </text>
                </Match>
              </Switch>
            </box>
          </Show>
        </box>
      </box>
    </>
  )
}
