import type { Snapshot } from "@/snapshot"

type NormalizedFileDiff = Snapshot.FileDiff & {
  beforePresent: boolean
  afterPresent: boolean
}

function count(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0
}

function text(value: unknown) {
  return typeof value === "string" ? value : ""
}

function normalizeItem(value: unknown): NormalizedFileDiff | undefined {
  if (!value || typeof value !== "object") return
  const item = value as Record<string, unknown>
  const file = text(item.file).trim()
  if (!file) return
  const beforePresent = Object.prototype.hasOwnProperty.call(item, "before")
  const afterPresent = Object.prototype.hasOwnProperty.call(item, "after")
  return {
    file,
    before: text(item.before),
    after: text(item.after),
    beforePresent,
    afterPresent,
    additions: count(item.additions),
    deletions: count(item.deletions),
  }
}

function publicDiff(item: NormalizedFileDiff): Snapshot.FileDiff {
  const { beforePresent: _beforePresent, afterPresent: _afterPresent, ...diff } = item
  return diff
}

export function normalizeSessionDiff(value: unknown): Snapshot.FileDiff[] {
  if (!Array.isArray(value)) return []

  const byFile = new Map<string, NormalizedFileDiff>()
  for (const raw of value) {
    const item = normalizeItem(raw)
    if (!item) continue
    const existing = byFile.get(item.file)
    if (!existing) {
      byFile.set(item.file, item)
      continue
    }
    byFile.set(item.file, {
      file: item.file,
      before: existing.beforePresent ? existing.before : item.before,
      after: item.afterPresent ? item.after : existing.after,
      beforePresent: existing.beforePresent || item.beforePresent,
      afterPresent: item.afterPresent || existing.afterPresent,
      additions: existing.additions + item.additions,
      deletions: existing.deletions + item.deletions,
    })
  }

  return Array.from(byFile.values())
    .map(publicDiff)
    .sort((left, right) => left.file.localeCompare(right.file))
}
