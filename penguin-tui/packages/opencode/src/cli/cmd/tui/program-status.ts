import { terminalSequence } from "./terminal-compat"

type Snapshot = {
  sessionID?: string
  errorID?: string
  busy: boolean
  permission: boolean
  question: boolean
  connection: "idle" | "connecting" | "connected" | "reconnecting" | "denied"
}

type State = "idle" | "working" | "done" | "blocked" | "error"

export type ProgramStatusReport = {
  state: State
  message: string
  kind?: "permission" | "question" | "auth"
}

// ponytail: one root record for the selected session; add child records only
// when the TUI subscribes to background sessions too.
export function createProgramStatus(options: {
  enabled: boolean
  write: (text: string) => void
  tmux?: boolean
  onChange?: (report: ProgramStatusReport) => void
}) {
  let current: Snapshot | undefined
  let outcome: State = "idle"
  let cancelled = false
  let acknowledged = false
  let previous = ""

  function report(state: State, message: string, kind?: "permission" | "question" | "auth") {
    const body = `state=${state}:app=penguin${kind ? `:kind=${kind}` : ""}:msg=${Buffer.from(message).toString("base64")}`
    if (body === previous) return
    previous = body
    options.onChange?.({ state, message, kind })
    if (!options.enabled) return
    const sequence = `\x1b]7501;${body}\x1b\\`
    options.write(terminalSequence(sequence, options.tmux ? { TMUX: "1" } : {}))
  }

  function render() {
    if (!current) return
    if (current.connection === "denied") return report("blocked", "Authentication required", "auth")
    if (cancelled) return report("idle", "Waiting for a prompt")
    if (current.permission) return report("blocked", "Approval required", "permission")
    if (current.question) return report("blocked", "Answer required", "question")
    if (outcome === "error")
      return report(acknowledged ? "idle" : "error", acknowledged ? "Waiting for a prompt" : "Run failed")
    if (current.connection === "connecting" || current.connection === "reconnecting") {
      return report("working", "Connecting to Penguin")
    }
    if (current.busy) return report("working", "Working")
    if (outcome === "done" && !acknowledged) return report("done", "Run complete")
    report("idle", "Waiting for a prompt")
  }

  return {
    update(next: Snapshot) {
      const changed = !current || current.sessionID !== next.sessionID
      const started = current && !current.busy && next.busy
      if (changed || started) {
        outcome = "idle"
        cancelled = false
        acknowledged = false
      }
      if (!changed && !cancelled && next.errorID && next.errorID !== current?.errorID) outcome = "error"
      if (!changed && !cancelled && current?.busy && !next.busy && outcome !== "error") outcome = "done"
      current = next
      render()
    },
    interrupt(sessionID: string) {
      if (current?.sessionID !== sessionID) return
      cancelled = true
      outcome = "idle"
      render()
    },
    fail(sessionID: string) {
      if (current?.sessionID !== sessionID || cancelled) return
      outcome = "error"
      acknowledged = false
      render()
    },
    acknowledge() {
      if (outcome !== "done" && outcome !== "error") return
      acknowledged = true
      render()
    },
    dispose() {
      // Preserve completed/failed results after exit, as required by OSC 7501.
      if (previous.startsWith("state=done:") || previous.startsWith("state=error:")) return
      report("idle", "Waiting for a prompt")
    },
  }
}
