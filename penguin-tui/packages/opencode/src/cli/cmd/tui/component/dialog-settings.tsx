import { TextAttributes } from "@opentui/core"
import { useSDK } from "@tui/context/sdk"
import { createMemo, createSignal, For, onMount, Show } from "solid-js"
import { useTheme } from "../context/theme"

type Location = {
  path?: string
  exists?: boolean
}

type Settings = {
  runtime?: {
    project_root?: string
    workspace_root?: string
    execution_mode?: string
    active_root?: string
  }
  locations?: {
    project?: {
      root?: string
      dir?: string
      config?: Location
      local?: Location
    }
    global?: {
      config?: Location
    }
  }
}

type Payload = {
  settings?: Settings
}

type Row = {
  label: string
  value?: string
  exists?: boolean
}

export function DialogSettings(props: { directory?: string; sessionID?: string }) {
  const { theme } = useTheme()
  const sdk = useSDK()
  const [loading, setLoading] = createSignal(true)
  const [error, setError] = createSignal<string>()
  const [settings, setSettings] = createSignal<Settings>()

  onMount(async () => {
    const url = new URL("/api/v1/system/settings", sdk.url)
    if (props.directory) url.searchParams.set("directory", props.directory)
    if (props.sessionID) url.searchParams.set("session_id", props.sessionID)

    const result = await fetch(url)
      .then((res) => (res.ok ? res.json() : undefined))
      .catch(() => undefined)

    if (!result || typeof result !== "object") {
      setError("Failed to load configuration from server")
      setLoading(false)
      return
    }

    const payload = result as Payload
    if (!payload.settings) {
      setError("Configuration payload was empty")
      setLoading(false)
      return
    }

    setSettings(payload.settings)
    setLoading(false)
  })

  const rows = createMemo<Row[]>(() => {
    const data = settings()
    if (!data) return []

    const project = data.locations?.project
    const global = data.locations?.global?.config
    const runtime = data.runtime

    return [
      { label: "project local override", value: project?.local?.path, exists: project?.local?.exists },
      { label: "project config", value: project?.config?.path, exists: project?.config?.exists },
      { label: "global config", value: global?.path, exists: global?.exists },
      { label: "session directory", value: props.directory },
      { label: "project root", value: project?.root },
      { label: "config directory", value: project?.dir },
      { label: "execution mode", value: runtime?.execution_mode },
      { label: "runtime root (server)", value: runtime?.active_root },
      { label: "workspace root (server)", value: runtime?.workspace_root },
      { label: "runtime project root (server)", value: runtime?.project_root },
    ].filter((item) => !!item.value)
  })

  return (
    <box paddingLeft={2} paddingRight={2} gap={1} paddingBottom={1}>
      <box flexDirection="row" justifyContent="space-between">
        <text fg={theme.text} attributes={TextAttributes.BOLD}>
          Configuration
        </text>
        <text fg={theme.textMuted}>read-only | esc</text>
      </box>
      <text fg={theme.textMuted} wrapMode="word">
        Use Ctrl+P for interactive controls: Switch model, Switch theme, View status, Connect provider.
      </text>
      <Show when={loading()}>
        <text fg={theme.textMuted}>Loading configuration...</text>
      </Show>
      <Show when={error()}>
        {(value) => <text fg={theme.error}>{value()}</text>}
      </Show>
      <Show when={!loading() && !error()}>
        <Show when={rows().length > 0} fallback={<text fg={theme.textMuted}>No configuration data available</text>}>
          <For each={rows()}>
            {(item) => (
              <text fg={theme.text} wrapMode="word">
                <b>{item.label}:</b>{" "}
                <span style={{ fg: theme.textMuted }}>
                  {item.value}
                  {item.exists === false ? " (missing)" : ""}
                </span>
              </text>
            )}
          </For>
        </Show>
      </Show>
    </box>
  )
}
