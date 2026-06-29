import { fileAutocompleteURL } from "./file-url"

type PromptFilePart = {
  type: "file"
  mime: string
  filename: string
  url: string
  source: {
    type: "file"
    path: string
    text: {
      start: number
      end: number
      value: string
    }
  }
}

type ExistingPromptPart = {
  type: string
  url?: unknown
  source?: unknown
}

const INLINE_FILE_REFERENCE_PATTERN = /(?<![\w`])@(\.?[^\s`,.]*(?:\.[^\s`,.]+)*)/g

function sourcePath(part: ExistingPromptPart): string | undefined {
  if (part.type !== "file") return undefined
  if (!part.source || typeof part.source !== "object") return undefined
  const value = (part.source as { path?: unknown }).path
  return typeof value === "string" && value.trim() ? value.trim() : undefined
}

function existingFileKeys(parts: ExistingPromptPart[]) {
  const keys = new Set<string>()
  for (const part of parts) {
    if (part.type !== "file") continue
    if (typeof part.url === "string" && part.url.trim()) keys.add(`url:${part.url.trim()}`)
    const path = sourcePath(part)
    if (path) keys.add(`path:${path}`)
  }
  return keys
}

function isFileLikeReference(value: string) {
  const path = value.split("#", 1)[0].split("?", 1)[0]
  return (
    path.includes(".") ||
    path.startsWith("/") ||
    path.startsWith("./") ||
    path.startsWith("../") ||
    path.startsWith("~/")
  )
}

export function inlineFileReferenceParts(input: {
  text: string
  directory: string
  existingParts?: ExistingPromptPart[]
}): PromptFilePart[] {
  const existing = existingFileKeys(input.existingParts ?? [])
  const seen = new Set<string>()
  const parts: PromptFilePart[] = []

  for (const match of input.text.matchAll(INLINE_FILE_REFERENCE_PATTERN)) {
    const reference = match[1]?.trim()
    if (!reference) continue
    if (!isFileLikeReference(reference)) continue
    const start = match.index ?? 0
    const value = `@${reference}`
    const url = fileAutocompleteURL({
      baseDirectory: input.directory,
      item: reference,
    })
    const pathKey = `path:${reference}`
    const urlKey = `url:${url}`
    if (seen.has(pathKey) || existing.has(pathKey) || existing.has(urlKey)) continue
    seen.add(pathKey)
    seen.add(urlKey)
    parts.push({
      type: "file",
      mime: "text/plain",
      filename: reference,
      url,
      source: {
        type: "file",
        path: reference,
        text: {
          start,
          end: start + value.length,
          value,
        },
      },
    })
  }

  return parts
}
