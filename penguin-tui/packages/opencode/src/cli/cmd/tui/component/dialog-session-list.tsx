import { useDialog } from "@tui/ui/dialog"
import { DialogSelect } from "@tui/ui/dialog-select"
import { useRoute } from "@tui/context/route"
import { useSync } from "@tui/context/sync"
import { createMemo, createSignal, createResource, onMount, Show } from "solid-js"
import { Locale } from "@/util/locale"
import { useKeybind } from "../context/keybind"
import { useTheme } from "../context/theme"
import { useSDK } from "../context/sdk"
import type { PenguinSession } from "../context/sync-bootstrap"
import { DialogSessionRename } from "./dialog-session-rename"
import { useKV } from "../context/kv"
import { createDebouncedSignal } from "../util/signal"
import {
  expandSessionSearchResults,
  formatSessionListTitle,
  getSessionListEntries,
  upsertSessionRecord,
} from "../util/session-family"
import type { Session } from "@opencode-ai/sdk/v2"
import "opentui-spinner/solid"

// TODO: Replace this deep fixed fetch with paginated/cursor loading once the
// Penguin session dialog has backend pagination and incremental list rendering.
const PENGUIN_SESSION_DIALOG_LIMIT = 1000
const OPENCODE_SESSION_SEARCH_LIMIT = 30

function isBlankPenguinSession(session: Session | PenguinSession) {
  const penguin = session as PenguinSession
  const fallbackTitle = penguin.fallback_title === true
  return fallbackTitle && penguin.display_message_count === 0
}

export function DialogSessionList() {
  const dialog = useDialog()
  const route = useRoute()
  const sync = useSync()
  const keybind = useKeybind()
  const { theme } = useTheme()
  const sdk = useSDK()
  const kv = useKV()

  const [toDelete, setToDelete] = createSignal<string>()
  const [search, setSearch] = createDebouncedSignal("", 150)
  const sessionListQuery = createMemo(() => ({
    directory: sync.data.path.directory || sdk.directory,
    search: search(),
  }))

  const [searchResults] = createResource(sessionListQuery, async (input) => {
    const query = input.search.trim()
    if (sdk.penguin) {
      const url = new URL("/session", sdk.url)
      if (input.directory) url.searchParams.set("directory", input.directory)
      url.searchParams.set("limit", String(PENGUIN_SESSION_DIALOG_LIMIT))
      if (query) url.searchParams.set("search", query)

      const response = await sdk.fetch(url)
      if (!response.ok) return undefined
      const data = await response.json().catch(() => undefined)
      return Array.isArray(data) ? (data as PenguinSession[]) : undefined
    }

    if (!query) return undefined
    const result = await sdk.client.session.list({ search: query, limit: OPENCODE_SESSION_SEARCH_LIMIT })
    return result.data ?? []
  })

  const currentSessionID = createMemo(() => (route.data.type === "session" ? route.data.sessionID : undefined))

  const spinnerFrames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

  const sessions = createMemo(() =>
    expandSessionSearchResults(searchResults(), sync.data.session).filter(
      (session) => !sdk.penguin || !isBlankPenguinSession(session),
    ),
  )

  const options = createMemo(() => {
    const today = new Date().toDateString()
    return getSessionListEntries(sessions()).map((entry) => {
      const x = entry.session
      const date = new Date(entry.familyTime)
      let category = date.toDateString()
      if (category === today) {
        category = "Today"
      }
      const isDeleting = toDelete() === x.id
      const status = sync.data.session_status?.[x.id]
      const isWorking = status?.type === "busy"
      return {
        title: isDeleting
          ? `Press ${keybind.print("session_delete")} again to confirm`
          : formatSessionListTitle(x.title, entry.depth),
        bg: isDeleting ? theme.error : undefined,
        value: x.id,
        category,
        description: entry.depth > 0 ? entry.parent?.title : undefined,
        footer: Locale.time(x.time.updated),
        gutter: isWorking ? (
          <Show when={kv.get("animations_enabled", true)} fallback={<text fg={theme.textMuted}>[⋯]</text>}>
            <spinner frames={spinnerFrames} interval={80} color={theme.primary} />
          </Show>
        ) : undefined,
      }
    })
  })

  onMount(() => {
    dialog.setSize("large")
  })

  return (
    <DialogSelect
      title="Sessions"
      options={options()}
      skipFilter={true}
      current={currentSessionID()}
      onFilter={setSearch}
      onMove={() => {
        setToDelete(undefined)
      }}
      onSelect={(option) => {
        const selected = sessions().find((item) => item.id === option.value)
        if (selected) {
          sync.set("session", upsertSessionRecord(sync.data.session, selected))
        }
        route.navigate({
          type: "session",
          sessionID: option.value,
        })
        dialog.clear()
      }}
      keybind={[
        {
          keybind: keybind.all.session_delete?.[0],
          title: "delete",
          onTrigger: async (option) => {
            if (toDelete() === option.value) {
              sdk.client.session.delete({
                sessionID: option.value,
              })
              setToDelete(undefined)
              return
            }
            setToDelete(option.value)
          },
        },
        {
          keybind: keybind.all.session_rename?.[0],
          title: "rename",
          onTrigger: async (option) => {
            dialog.replace(() => <DialogSessionRename session={option.value} />)
          },
        },
      ]}
    />
  )
}
