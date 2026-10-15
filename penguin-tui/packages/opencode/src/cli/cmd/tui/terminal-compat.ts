import type { ProgramStatusReport } from "./program-status"

export function isCmux(env: NodeJS.ProcessEnv): boolean {
  return Boolean(
    env.CMUX ||
      env.CMUX_SESSION ||
      env.CMUX_SESSION_ID ||
      env.CMUX_WORKSPACE_ID ||
      env.CMUX_SOCKET ||
      env.CMUX_SOCKET_PATH ||
      env.CMUX_PANE ||
      env.TERM_PROGRAM?.toLowerCase() === "cmux",
  )
}

export function terminalNotificationProtocol(env: NodeJS.ProcessEnv = process.env) {
  const override = env.PENGUIN_TUI_NOTIFICATION_PROTOCOL
  if (override === "osc9" || override === "osc99" || override === "osc777" || override === "bell") return override
  if (isCmux(env)) return "osc777"
  const program = env.TERM_PROGRAM?.toLowerCase()
  if (program === "wezterm") return "osc777"
  if (program === "kitty" || env.KITTY_WINDOW_ID || env.TERM === "xterm-kitty") return "osc99"
  if (program === "iterm.app" || program === "iterm_app" || program === "ghostty") return "osc9"
  // Apple Terminal and unknown/remote terminals have no universal notification OSC.
  return "bell"
}

export function terminalSequence(sequence: string, env: NodeJS.ProcessEnv = process.env): string {
  if (!env.TMUX || sequence === "\x07") return sequence
  return `\x1bPtmux;${sequence.replaceAll("\x1b", "\x1b\x1b")}\x1b\\`
}

export function terminalProgramTitle(report: ProgramStatusReport, title: string): string {
  const labels = { idle: "Idle", working: "Working", blocked: "Needs input", done: "Done", error: "Error" }
  return `[${labels[report.state]}] ${title.replace(/[\u0000-\u001f\u007f-\u009f]/g, " ")}`
}
