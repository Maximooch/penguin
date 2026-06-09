import type { Session } from "@opencode-ai/sdk/v2"
import type { PenguinSession } from "../context/sync-bootstrap"
import { expandSessionSearchResults } from "./session-family"

type DialogSession = Session | PenguinSession

export function isBlankPenguinSession(session: DialogSession) {
  const penguin = session as PenguinSession
  const fallbackTitle = penguin.fallback_title === true
  return fallbackTitle && penguin.display_message_count === 0
}

export function appendSessionIfMissing<T extends { id: string }>(sessions: T[], session: T | undefined) {
  if (!session) return sessions
  if (sessions.some((item) => item.id === session.id)) return sessions
  return [...sessions, session]
}

export function getDialogSessions(input: {
  activeSessionID?: string
  cachedSessions: DialogSession[]
  penguin: boolean
  searchQuery: string
  searchResults?: DialogSession[]
}) {
  const currentSession = input.cachedSessions.find((item) => item.id === input.activeSessionID)
  const expanded = expandSessionSearchResults(input.searchResults, input.cachedSessions)
  const withCurrent =
    input.penguin && !input.searchQuery.trim() ? appendSessionIfMissing(expanded, currentSession) : expanded

  return withCurrent.filter(
    (session) => !input.penguin || session.id === input.activeSessionID || !isBlankPenguinSession(session),
  )
}
