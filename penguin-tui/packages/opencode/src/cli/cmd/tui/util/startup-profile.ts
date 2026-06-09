const STARTUP_PROFILE =
  process.env.PENGUIN_TUI_PROFILE === "1" ||
  process.env.OPENCODE_TUI_PROFILE === "1"

export function profileStartup(label: string, details: Record<string, unknown> = {}) {
  if (!STARTUP_PROFILE) return
  console.log("[penguin-tui startup]", {
    label,
    ms: Math.round(performance.now()),
    ...details,
  })
}
