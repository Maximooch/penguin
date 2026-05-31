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
  text: string
}): PenguinFastCommandResult {
  const [command, argument = ""] = input.text.trim().split(/\s+/, 2)
  if (command !== "/fast") return { matched: false }

  const value = argument.toLowerCase()
  if (!value) {
    input.fast.toggle()
  } else if (value === "on") {
    input.fast.set(true)
  } else if (value === "off") {
    input.fast.set(false)
  } else if (value !== "status") {
    return {
      matched: true,
      message: "Usage: /fast [on|off|status]",
      variant: "warning",
    }
  }

  return {
    matched: true,
    message: formatPenguinFastModeStatus(input.fast.enabled()),
    variant: "info",
  }
}
