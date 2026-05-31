import fs from "fs"
import path from "path"

type SyncEvent = {
  type: string
  properties: unknown
}

const DIRECTORY_SCOPED_EVENTS = new Set([
  "lsp.updated",
  "lsp.client.diagnostics",
  "vcs.branch.updated",
])

export function normalizeSyncDirectory(value?: string): string | undefined {
  if (!value || typeof value !== "string") return undefined
  const trimmed = value.trim()
  if (!trimmed) return undefined
  const resolved = (() => {
    try {
      if (fs.realpathSync.native) return fs.realpathSync.native(trimmed)
    } catch {
      // Fall back below.
    }
    try {
      return fs.realpathSync(trimmed)
    } catch {
      // Fall back below.
    }
    try {
      return path.resolve(trimmed)
    } catch {
      return trimmed
    }
  })()
  return resolved.replace(/\\/g, "/")
}

export function extractSyncEventSessionID(event: { properties: unknown }): string | undefined {
  const props = event.properties
  if (!props || typeof props !== "object") return undefined
  const root = props as Record<string, unknown>
  const direct = root.sessionID ?? root.session_id ?? root.conversation_id
  if (typeof direct === "string" && direct) return direct
  const info = root.info
  if (info && typeof info === "object") {
    const infoSession =
      (info as Record<string, unknown>).sessionID ??
      (info as Record<string, unknown>).session_id ??
      (info as Record<string, unknown>).conversation_id
    if (typeof infoSession === "string" && infoSession) return infoSession
  }
  const part = root.part
  if (part && typeof part === "object") {
    const partSession =
      (part as Record<string, unknown>).sessionID ??
      (part as Record<string, unknown>).session_id ??
      (part as Record<string, unknown>).conversation_id
    if (typeof partSession === "string" && partSession) return partSession
  }
  return undefined
}

export function extractSyncEventDirectory(event: { properties: unknown }): string | undefined {
  const props = event.properties
  if (!props || typeof props !== "object") return undefined
  const root = props as Record<string, unknown>
  if (typeof root.directory === "string" && root.directory) return root.directory
  const info = root.info
  if (info && typeof info === "object") {
    const infoRoot = info as Record<string, unknown>
    if (typeof infoRoot.directory === "string" && infoRoot.directory) return infoRoot.directory
    const pathRoot = infoRoot.path
    if (pathRoot && typeof pathRoot === "object") {
      const cwd = (pathRoot as Record<string, unknown>).cwd
      if (typeof cwd === "string" && cwd) return cwd
    }
  }
  const pathRoot = root.path
  if (pathRoot && typeof pathRoot === "object") {
    const cwd = (pathRoot as Record<string, unknown>).cwd
    if (typeof cwd === "string" && cwd) return cwd
  }
  const part = root.part
  if (part && typeof part === "object") {
    const partRoot = part as Record<string, unknown>
    if (typeof partRoot.directory === "string" && partRoot.directory) return partRoot.directory
  }
  return undefined
}

export function shouldIgnorePenguinScopedEvent(input: {
  activeSessionID?: string
  appDirectory?: string
  event: SyncEvent
  sessionDirectory: (sessionID?: string) => string | undefined
}): boolean {
  const sid = extractSyncEventSessionID(input.event)
  const dir = normalizeSyncDirectory(extractSyncEventDirectory(input.event))
  const baseDir = input.appDirectory

  if (input.activeSessionID) {
    if (sid && sid !== input.activeSessionID) return true
    const activeDir = input.sessionDirectory(input.activeSessionID) ?? baseDir
    if (!sid) {
      if (dir && activeDir && dir !== activeDir) return true
      if (!dir && DIRECTORY_SCOPED_EVENTS.has(input.event.type)) return true
    }
    return false
  }

  if (sid) {
    const sidDir = input.sessionDirectory(sid)
    if (sidDir && baseDir && sidDir !== baseDir) return true
    if (!sidDir && dir && baseDir && dir !== baseDir) return true
    return false
  }

  if (dir && baseDir && dir !== baseDir) return true
  return !dir && DIRECTORY_SCOPED_EVENTS.has(input.event.type)
}
