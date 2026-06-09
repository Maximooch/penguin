import { removeSessionRecord, upsertSessionRecord } from "../util/session-family"

type SessionRecord = {
  id: string
}

type SessionListEvent<T extends SessionRecord> =
  | {
      type: "session.created" | "session.updated"
      properties?: {
        info?: T
      }
    }
  | {
      type: "session.deleted"
      properties?: {
        info?: Partial<SessionRecord>
      }
    }

export function applySessionListEvent<T extends SessionRecord>(sessions: T[], event: SessionListEvent<T>): T[] {
  switch (event.type) {
    case "session.created":
    case "session.updated": {
      const info = event.properties?.info
      if (!info?.id) return sessions
      return upsertSessionRecord(sessions, info)
    }
    case "session.deleted": {
      const sessionID = event.properties?.info?.id
      if (!sessionID) return sessions
      if (!sessions.some((item) => item.id === sessionID)) return sessions
      return removeSessionRecord(sessions, sessionID)
    }
  }
}
