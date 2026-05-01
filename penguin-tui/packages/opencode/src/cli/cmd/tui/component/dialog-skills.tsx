import { TextAttributes } from "@opentui/core"
import { createMemo, createSignal, onMount } from "solid-js"
import { useSDK } from "@tui/context/sdk"
import { useTheme } from "../context/theme"
import { useToast } from "../ui/toast"
import { DialogSelect, type DialogSelectOption } from "@tui/ui/dialog-select"
import { Keybind } from "@/util/keybind"

type SkillEntry = {
  name: string
  description: string
  source?: string
  path?: string
  active?: boolean
}

type SkillDiagnostic = {
  path?: string
  message?: string
  severity?: string
}

type SkillCatalogPayload = {
  skills?: SkillEntry[]
  diagnostics?: SkillDiagnostic[]
  count?: number
  diagnostic_count?: number
  active?: string[]
}

type SkillOption =
  | { kind: "skill"; name: string }
  | { kind: "diagnostic"; index: number }
  | { kind: "help"; id: "install" }
  | { kind: "status"; id: "loading" | "error" }

function Status(props: { active?: boolean; loading?: boolean }) {
  const { theme } = useTheme()
  if (props.loading) return <span style={{ fg: theme.textMuted }}>⋯ Updating</span>
  if (props.active) return <span style={{ fg: theme.success, attributes: TextAttributes.BOLD }}>✓ Active</span>
  return <span style={{ fg: theme.textMuted }}>○ Available</span>
}

function installGuidance() {
  return "Install manually by copying a skill folder into ~/.penguin/skills or .penguin/skills, then refresh this panel."
}

function summarize(value: string | undefined, max = 42) {
  if (!value) return undefined
  const compact = value.replace(/\s+/g, " ").trim()
  if (compact.length <= max) return compact
  return `${compact.slice(0, Math.max(0, max - 1)).trimEnd()}…`
}

export function DialogSkills() {
  const sdk = useSDK()
  const toast = useToast()
  const { theme } = useTheme()
  const [payload, setPayload] = createSignal<SkillCatalogPayload>({})
  const [loading, setLoading] = createSignal(true)
  const [activating, setActivating] = createSignal<string | null>(null)
  const [error, setError] = createSignal<string>()

  async function load(refresh = false) {
    setLoading(true)
    setError(undefined)
    const url = new URL("/api/v1/skills", sdk.url)
    if (sdk.sessionID) url.searchParams.set("session_id", sdk.sessionID)
    if (refresh) url.searchParams.set("refresh", "true")

    try {
      const res = await sdk.fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setPayload((await res.json()) as SkillCatalogPayload)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(`Failed to load skills: ${message}`)
    } finally {
      setLoading(false)
    }
  }

  async function toggleSkill(skill: SkillEntry) {
    if (activating() !== null) return
    setActivating(skill.name)
    try {
      const action = skill.active ? "deactivate" : "activate"
      const url = new URL(`/api/v1/skills/${encodeURIComponent(skill.name)}/${action}`, sdk.url)
      const body = skill.active
        ? { session_id: sdk.sessionID ?? "default" }
        : { session_id: sdk.sessionID ?? "default", load_into_context: true }
      const res = await sdk.fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const result = (await res.json()) as { status?: string; duplicate?: boolean; was_active?: boolean }
      toast.show({
        variant: result.status === "not_active" || result.duplicate ? "info" : "success",
        message: skill.active ? `Deactivated ${skill.name}` : `Activated ${skill.name}`,
      })
      await load(false)
    } catch (err) {
      toast.error(err instanceof Error ? err : new Error(String(err)))
    } finally {
      setActivating(null)
    }
  }

  onMount(() => {
    load(false)
  })

  const options = createMemo<DialogSelectOption<SkillOption>[]>(() => {
    const diagnostics = payload().diagnostics ?? []
    const skills = payload().skills ?? []
    const result: DialogSelectOption<SkillOption>[] = []

    if (error()) {
      result.push({
        title: "Skills unavailable",
        value: { kind: "status", id: "error" },
        description: summarize(error(), 52),
        footer: "Check penguin-web logs, then reopen this panel.",
        category: "Diagnostics",
      })
    }

    for (const [index, diagnostic] of diagnostics.entries()) {
      result.push({
        title: diagnostic.severity ? `${diagnostic.severity}: invalid skill` : "Invalid skill",
        value: { kind: "diagnostic", index },
        description: summarize(diagnostic.message, 52),
        footer: summarize(diagnostic.path, 48) ?? "No path reported",
        category: "Diagnostics",
      })
    }

    for (const skill of skills) {
      result.push({
        title: skill.name,
        value: { kind: "skill", name: skill.name },
        description: summarize(skill.description),
        footer: <Status active={skill.active} loading={activating() === skill.name} />,
        category: skill.active ? "Active" : "Available",
      })
    }

    result.push({
      title: "Install skills manually",
      value: { kind: "help", id: "install" },
      description: summarize(installGuidance(), 52),
      footer: "~/.penguin/skills · .penguin/skills",
      category: "Help",
    })

    if (loading() && skills.length === 0 && diagnostics.length === 0) {
      result.unshift({
        title: "Loading skills...",
        value: { kind: "status", id: "loading" },
        description: "Fetching catalog",
        footer: <span style={{ fg: theme.textMuted }}>Please wait</span>,
        category: "Status",
      })
    }

    return result
  })

  const keybinds = createMemo(() => [
    {
      keybind: Keybind.parse("space")[0],
      title: "toggle",
      disabled: activating() !== null,
      onTrigger: (option: DialogSelectOption<SkillOption>) => {
        const selected = option.value
        if (selected.kind !== "skill") return
        const skill = payload().skills?.find((entry) => entry.name === selected.name)
        if (!skill) return
        toggleSkill(skill)
      },
    },
    {
      keybind: Keybind.parse("ctrl+r")[0],
      title: "refresh",
      disabled: loading(),
      onTrigger: () => load(true),
    },
  ])

  return (
    <DialogSelect
      title="Skills"
      placeholder="Search skills"
      options={options()}
      keybind={keybinds()}
      onSelect={() => {
        // Deliberately no auto-activation on selection. Use Space to activate/deactivate.
      }}
    />
  )
}
