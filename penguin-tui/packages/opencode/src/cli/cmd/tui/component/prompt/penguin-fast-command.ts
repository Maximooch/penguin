export type PenguinFastMode = {
  enabled(): boolean
  set(value: boolean | undefined): void
  toggle(): void
}

export type PenguinFastCommandResult =
  | {
      matched: false
    }
  | {
      matched: true
      message: string
      variant: "info" | "warning"
    }

export function formatPenguinFastModeStatus(enabled: boolean): string {
  return enabled ? "Fast mode on" : "Fast mode off"
}

export function applyPenguinFastCommand(input: {
  fast: PenguinFastMode
  ultrafast?: PenguinFastMode
  text: string
}): PenguinFastCommandResult {
  const [command, argument = "", ...extra] = input.text.trim().split(/\s+/)
  const mode = command === "/fast" ? input.fast : command === "/ultrafast" ? input.ultrafast : undefined
  if (!mode) return { matched: false }
  const name = command === "/ultrafast" ? "Ultrafast" : "Fast"
  const value = argument.toLowerCase()
  if (extra.length || !["", "on", "off", "status"].includes(value)) {
    return {
      matched: true,
      message: `Usage: ${command} [on|off|status]`,
      variant: "warning",
    }
  }
  if (!value) {
    mode.toggle()
  } else if (value === "on") {
    mode.set(true)
  } else if (value === "off") {
    mode.set(false)
  }

  return {
    matched: true,
    message: `${name} mode ${mode.enabled() ? "on" : "off"}`,
    variant: "info",
  }
}
