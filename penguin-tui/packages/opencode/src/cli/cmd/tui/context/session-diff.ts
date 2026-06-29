import type { Snapshot } from "@/snapshot"

function count(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0
}

function text(value: unknown) {
  return typeof value === "string" ? value : ""
}

function normalizeItem(value: unknown): Snapshot.FileDiff | undefined {
  if (!value || typeof value !== "object") return
  const item = value as Record<string, unknown>
  const file = text(item.file).trim()
  if (!file) return
  return {
    file,
    before: text(item.before),
    after: text(item.after),
    additions: count(item.additions),
    deletions: count(item.deletions),
  }
}

export function normalizeSessionDiff(value: unknown): Snapshot.FileDiff[] {
  if (!Array.isArray(value)) return []

  const byFile = new Map<string, Snapshot.FileDiff>()
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
      before: existing.before || item.before,
      after: item.after || existing.after,
      additions: existing.additions + item.additions,
      deletions: existing.deletions + item.deletions,
    })
  }

  return Array.from(byFile.values()).sort((left, right) => left.file.localeCompare(right.file))
}
