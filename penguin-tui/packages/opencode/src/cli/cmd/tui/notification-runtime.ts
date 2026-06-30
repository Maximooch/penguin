import {
  notificationPayloads,
  type AttentionEvent,
  type NotificationPayload,
  type NotificationPolicy,
} from "./notification-policy"
import { existsSync } from "node:fs"
import { delimiter, dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

type SyncEvent = {
  type: string
  properties?: Record<string, unknown>
}

export type NotificationDeliveryOptions = {
  assets?: NotificationAssets
  write?: (text: string) => void
  log?: (payload: NotificationPayload) => void
  spawn?: (command: string[]) => void
  platform?: NodeJS.Platform
}

export type NotificationAssets = {
  icon?: string
  terminalApp?: string
  terminalBundleID?: string
  terminalNotifier?: string
  sounds?: Partial<Record<string, string>>
}

export type TerminalNotificationIdentity = {
  app?: string
  bundleID?: string
}

const CMUX_BUNDLE_ID = "com.cmuxterm.app"

const TERMINAL_IDENTITIES: Record<string, Required<TerminalNotificationIdentity>> = {
  Apple_Terminal: {
    app: "Apple Terminal",
    bundleID: "com.apple.Terminal",
  },
  ghostty: {
    app: "Ghostty",
    bundleID: "com.mitchellh.ghostty",
  },
  Ghostty: {
    app: "Ghostty",
    bundleID: "com.mitchellh.ghostty",
  },
  iTerm_app: {
    app: "iTerm2",
    bundleID: "com.googlecode.iterm2",
  },
  "iTerm.app": {
    app: "iTerm2",
    bundleID: "com.googlecode.iterm2",
  },
  vscode: {
    app: "VS Code terminal",
    bundleID: "com.microsoft.VSCode",
  },
  WezTerm: {
    app: "WezTerm",
    bundleID: "com.github.wez.wezterm",
  },
  kitty: {
    app: "Kitty",
    bundleID: "net.kovidgoyal.kitty",
  },
  WarpTerminal: {
    app: "Warp",
    bundleID: "dev.warp.Warp-Stable",
  },
  Hyper: {
    app: "Hyper",
    bundleID: "co.zeit.hyper",
  },
  cmux: {
    app: "CMUX",
    bundleID: CMUX_BUNDLE_ID,
  },
  CMUX: {
    app: "CMUX",
    bundleID: CMUX_BUNDLE_ID,
  },
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined
}

function statusType(value: unknown): string | undefined {
  if (!value || typeof value !== "object") return
  const status = value as Record<string, unknown>
  return stringValue(status.type)
}

export function attentionEventFromSyncEvent(event: SyncEvent): AttentionEvent | undefined {
  const properties = event.properties ?? {}
  const sessionID = stringValue(properties.sessionID)
  if (event.type === "session.idle") {
    return {
      category: "run_complete",
      sessionID,
      title: "Penguin run complete",
      message: stringValue(properties.title) ?? stringValue(properties.message),
    }
  }
  if (event.type === "session.status" && statusType(properties.status) === "idle") {
    return {
      category: "run_complete",
      sessionID,
      title: "Penguin run complete",
      message: stringValue(properties.title) ?? stringValue(properties.message),
    }
  }
  if (event.type === "permission.asked") {
    return {
      category: "approval_waiting",
      sessionID,
      title: "Penguin needs approval",
      message: stringValue(properties.title) ?? stringValue(properties.reason),
    }
  }
  if (event.type === "question.asked") {
    return {
      category: "question_waiting",
      sessionID,
      title: "Penguin has a question",
      message: stringValue(properties.question) ?? stringValue(properties.message),
    }
  }
  if (event.type === "session.error") {
    return {
      category: "run_failed",
      sessionID,
      title: "Penguin run failed",
      message: stringValue(properties.error) ?? stringValue(properties.message),
    }
  }
  return
}

export function notificationEventKey(event: SyncEvent): string | undefined {
  const properties = event.properties ?? {}
  const sessionID = stringValue(properties.sessionID) ?? ""
  const id =
    stringValue(properties.id) ??
    stringValue(properties.requestID) ??
    stringValue(properties.messageID) ??
    stringValue(properties.partID)
  if (!id && event.type === "session.error" && sessionID) return `${event.type}:${sessionID}`
  if (!id) return
  return `${event.type}:${sessionID}:${id}`
}

export function shouldSuppressNotificationForActiveSession(
  event: SyncEvent,
  options: {
    activeSessionID?: string
    terminalFocused?: boolean
  } = {},
): boolean {
  const terminalFocused = options.terminalFocused ?? true
  if (!terminalFocused || !options.activeSessionID) return false
  const attention = attentionEventFromSyncEvent(event)
  return Boolean(attention?.sessionID && attention.sessionID === options.activeSessionID)
}

export function notificationEscape(payload: NotificationPayload): string | undefined {
  if (payload.channel === "bell") return "\u0007"
  if (payload.channel === "osc") {
    const title = notificationOscField(payload.title)
    const body = notificationOscField(payload.body)
    return `\u001b]9;${title};${body}\u0007`
  }
  if (payload.channel === "terminal") {
    const title = notificationOscField(payload.title)
    const body = notificationOscField(payload.body)
    return `\u001b]9;${title};${body}\u0007`
  }
  return
}

function notificationOscField(value: string): string {
  return value
    .replace(/[\u0000-\u001f\u007f-\u009f;\\\]]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
}

export function notificationCommand(
  payload: NotificationPayload,
  platform: NodeJS.Platform = process.platform,
  assets: NotificationAssets = {},
): string[] | undefined {
  if (payload.channel === "sound") {
    const sound = payload.sound ? assets.sounds?.[payload.sound] : undefined
    if (platform === "darwin" && sound) return ["/usr/bin/afplay", sound]
    if (platform === "linux" && sound) return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", sound]
    if (platform !== "darwin") return
    if (payload.sound?.startsWith("noot-noot")) return ["/usr/bin/say", "NOOT NOOT"]
    return ["/usr/bin/afplay", macOSSoundPath(payload.sound)]
  }

  if (payload.channel === "os") {
    if (platform === "linux") {
      const icon = assets.icon ? ["--icon", assets.icon] : []
      return [
        "notify-send",
        "--app-name=Penguin",
        "--expire-time=8000",
        "--urgency",
        notificationUrgency(payload.category),
        ...icon,
        payload.title,
        payload.body,
      ]
    }

    if (platform === "win32") {
      return [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        windowsToastScript(payload.title, payload.body, assets.icon),
      ]
    }

    if (platform !== "darwin") return
    if (assets.terminalNotifier) {
      const sender = assets.terminalBundleID ? ["-sender", assets.terminalBundleID] : []
      return [assets.terminalNotifier, "-title", payload.title, "-message", payload.body, ...sender]
    }
    const sound = payload.sound ? ` sound name ${appleScriptString(macOSNotificationSoundName(payload.sound))}` : ""
    const displayNotification = [
      "display notification ",
      appleScriptString(payload.body),
      " with title ",
      appleScriptString(payload.title),
      sound,
    ].join("")
    const script = assets.terminalBundleID
      ? `tell application id ${appleScriptString(assets.terminalBundleID)} to ${displayNotification}`
      : displayNotification
    return ["/usr/bin/osascript", "-e", script]
  }

  return
}

export function deliverNotificationPayloads(
  payloads: NotificationPayload[],
  options: NotificationDeliveryOptions = {},
): NotificationPayload[] {
  const assets = options.assets ?? bundledNotificationAssets()
  for (const payload of payloads) {
    const escape = notificationEscape(payload)
    if (escape && options.write) options.write(escape)
    const command = notificationCommand(payload, options.platform, assets)
    if (command) runNotificationCommand(command, options.spawn)
    if (options.log) options.log(payload)
  }
  return payloads
}

export function notifyForSyncEvent(
  event: SyncEvent,
  policy: NotificationPolicy,
  options: NotificationDeliveryOptions = {},
): NotificationPayload[] {
  const attention = attentionEventFromSyncEvent(event)
  if (!attention) return []
  return deliverNotificationPayloads(notificationPayloads(attention, policy), options)
}

function runNotificationCommand(command: string[], spawn = spawnNotificationCommand): void {
  try {
    spawn(command)
  } catch {
    // Notification delivery should never break the TUI event loop.
  }
}

function spawnNotificationCommand(command: string[]): void {
  Bun.spawn(command, {
    stdin: "ignore",
    stdout: "ignore",
    stderr: "ignore",
  })
}

function macOSSoundPath(sound: string | undefined): string {
  const name = macOSNotificationSoundName(sound)
  return `/System/Library/Sounds/${name}.aiff`
}

function bundledNotificationAssets(): NotificationAssets {
  const train = resolveAssetPath("penguin-tui/media/freesound_community-subway-station-chime-100558.mp3")
  const noot = resolveAssetPath("penguin-tui/media/noot_p0CPOIz.mp3")
  const terminalIdentity = terminalNotificationIdentity()
  return {
    icon: resolveAssetPath("docs/static/img/penguin.png") ?? resolveAssetPath("docs/static/img/favicon.ico"),
    terminalApp: terminalIdentity.app,
    terminalBundleID: terminalIdentity.bundleID,
    terminalNotifier: resolveTerminalNotifier(),
    sounds: {
      ...(train
        ? {
            arrival: train,
            "boarding-call": train,
            "delay-announcement": train,
            "platform-update": train,
            "service-disruption": train,
            "ticket-check": train,
          }
        : {}),
      ...(noot
        ? {
            "noot-noot": noot,
            "noot-noot-attention": noot,
            "noot-noot-update": noot,
            "noot-noot-warning": noot,
          }
        : {}),
    },
  }
}

function resolveTerminalNotifier(): string | undefined {
  const explicit = process.env.PENGUIN_TUI_TERMINAL_NOTIFIER
  if (explicit && existsSync(explicit)) return explicit
  return resolveCommandPath("terminal-notifier")
}

function resolveCommandPath(command: string): string | undefined {
  for (const directory of process.env.PATH?.split(delimiter) ?? []) {
    if (!directory) continue
    const candidate = join(directory, command)
    if (existsSync(candidate)) return candidate
  }
  for (const directory of ["/opt/homebrew/bin", "/usr/local/bin"]) {
    const candidate = join(directory, command)
    if (existsSync(candidate)) return candidate
  }
  return
}

export function terminalNotificationIdentity(env: NodeJS.ProcessEnv = process.env): TerminalNotificationIdentity {
  const explicit = env.PENGUIN_TUI_TERMINAL_BUNDLE_ID?.trim()
  const termProgram = env.TERM_PROGRAM?.trim()
  const identity = termProgram ? TERMINAL_IDENTITIES[termProgram] : undefined
  const fallback = detectsCMUX(env)
    ? {
        app: "CMUX",
        bundleID: CMUX_BUNDLE_ID,
      }
    : undefined
  const app = identity?.app ?? fallback?.app ?? termProgram ?? (env.TMUX ? "tmux" : undefined)
  const bundleID = explicit ?? identity?.bundleID ?? fallback?.bundleID
  return {
    app: app && env.TMUX ? `${app} via tmux` : app,
    bundleID,
  }
}

function detectsCMUX(env: NodeJS.ProcessEnv): boolean {
  return Boolean(
    env.CMUX ||
      env.CMUX_SESSION ||
      env.CMUX_SOCKET ||
      env.CMUX_PANE ||
      env.TERM_PROGRAM?.trim().toLowerCase() === "cmux",
  )
}

function resolveAssetPath(relative: string): string | undefined {
  const start = dirname(fileURLToPath(import.meta.url))
  let current = start
  while (true) {
    const candidate = join(current, relative)
    if (existsSync(candidate)) return candidate
    const parent = dirname(current)
    if (parent === current) return
    current = parent
  }
}

function macOSNotificationSoundName(sound: string | undefined): string {
  if (!sound) return "Ping"
  if (sound.includes("error") || sound.includes("warning") || sound.includes("disruption") || sound.includes("delay")) {
    return "Basso"
  }
  if (sound.includes("boarding") || sound.includes("attention") || sound.includes("ticket")) return "Glass"
  if (sound.includes("arrival") || sound.includes("complete")) return "Ping"
  if (sound.includes("platform") || sound.includes("update")) return "Pop"
  if (sound.startsWith("noot-noot")) return "Ping"
  return "Ping"
}

function appleScriptString(value: string): string {
  return JSON.stringify(value.replace(/[\u0000-\u001f\u007f]/g, " "))
}

function notificationUrgency(category: string): string {
  if (category === "run_failed" || category === "reconnect_failed" || category === "provider_auth") return "critical"
  return "normal"
}

function windowsToastScript(title: string, body: string, icon?: string): string {
  const safeTitle = powerShellSingleQuotedString(title)
  const safeBody = powerShellSingleQuotedString(body)
  const safeIcon = icon ? powerShellSingleQuotedString(icon) : undefined
  return [
    "Add-Type -AssemblyName System.Windows.Forms;",
    "Add-Type -AssemblyName System.Drawing;",
    "$n=New-Object System.Windows.Forms.NotifyIcon;",
    safeIcon
      ? `$n.Icon=New-Object System.Drawing.Icon -ArgumentList ${safeIcon};`
      : "$n.Icon=[System.Drawing.SystemIcons]::Information;",
    `$n.BalloonTipTitle=${safeTitle};`,
    `$n.BalloonTipText=${safeBody};`,
    "$n.Visible=$true;",
    "$n.ShowBalloonTip(8000);",
    "Start-Sleep -Milliseconds 8500;",
    "$n.Dispose();",
  ].join("")
}

function powerShellSingleQuotedString(value: string): string {
  return `'${value.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/'/g, "''")}'`
}
