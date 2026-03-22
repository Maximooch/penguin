import type { Session } from "@opencode-ai/sdk/v2"

type SessionLike = Pick<Session, "id" | "title" | "time"> & {
  parentID?: string
}

export type SessionListEntry<T extends SessionLike = Session> = {
  session: T
  parent?: T
  familyID: string
  familyTime: number
  depth: number
}

function compareFamilyMembers<T extends SessionLike>(left: T, right: T, familyID: string) {
  const leftRoot = left.id === familyID
  const rightRoot = right.id === familyID
  if (leftRoot && !rightRoot) return -1
  if (!leftRoot && rightRoot) return 1

  const created = left.time.created - right.time.created
  if (created !== 0) return created

  const updated = left.time.updated - right.time.updated
  if (updated !== 0) return updated

  return left.id.localeCompare(right.id)
}

function familyID<T extends SessionLike>(session: T) {
  return session.parentID ?? session.id
}

export function upsertSessionRecord<T extends { id: string }>(sessions: T[], next: T) {
  const index = sessions.findIndex((item) => item.id === next.id)
  if (index === -1) return [...sessions, next]
  return sessions.map((item, itemIndex) => (itemIndex === index ? next : item))
}

export function removeSessionRecord<T extends { id: string }>(sessions: T[], sessionID: string) {
  return sessions.filter((item) => item.id !== sessionID)
}

export function getSessionFamily<T extends SessionLike>(sessions: T[], sessionID: string) {
  const target = sessions.find((item) => item.id === sessionID)
  if (!target) return []

  const rootID = familyID(target)
  return sessions
    .filter((item) => familyID(item) === rootID)
    .toSorted((left, right) => compareFamilyMembers(left, right, rootID))
}

export function expandSessionSearchResults<T extends SessionLike>(results: T[] | undefined, cached: T[]) {
  if (!results) return cached

  const cache = new Map(cached.map((item) => [item.id, item]))
  const merged = new Map(results.map((item) => [item.id, item]))

  for (const item of results) {
    if (!item.parentID) continue
    if (merged.has(item.parentID)) continue
    const parent = cache.get(item.parentID)
    if (!parent) continue
    merged.set(parent.id, parent)
  }

  return [...merged.values()]
}

export function getSessionListEntries<T extends SessionLike>(sessions: T[]): SessionListEntry<T>[] {
  const lookup = new Map(sessions.map((item) => [item.id, item]))
  const grouped = new Map<string, T[]>()

  for (const item of sessions) {
    const rootID = familyID(item)
    const family = grouped.get(rootID) ?? []
    family.push(item)
    grouped.set(rootID, family)
  }

  return [...grouped.entries()]
    .map(([rootID, family]) => {
      const familyTime = Math.max(...family.map((item) => item.time.updated))
      const ordered = family.toSorted((left, right) => compareFamilyMembers(left, right, rootID))
      return ordered.map((session) => ({
        session,
        parent: session.parentID ? lookup.get(session.parentID) : undefined,
        familyID: rootID,
        familyTime,
        depth: session.id === rootID ? 0 : 1,
      }))
    })
    .toSorted((left, right) => {
      const time = right[0]!.familyTime - left[0]!.familyTime
      if (time !== 0) return time
      return left[0]!.familyID.localeCompare(right[0]!.familyID)
    })
    .flat()
}

export function formatSessionListTitle(title: string, depth: number) {
  if (depth <= 0) return title
  return `  > ${title}`
}
