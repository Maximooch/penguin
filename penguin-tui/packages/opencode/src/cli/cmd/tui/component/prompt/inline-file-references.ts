import { fileAutocompleteURL } from "./file-url"
import { existsSync } from "node:fs"
import { basename, extname, isAbsolute, join, normalize } from "node:path"

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
const FILE_REFERENCE_EXTENSIONS = new Set([
  ".c",
  ".cpp",
  ".cs",
  ".css",
  ".csv",
  ".env",
  ".fish",
  ".gif",
  ".go",
  ".h",
  ".hpp",
  ".html",
  ".java",
  ".jpeg",
  ".jpg",
  ".js",
  ".json",
  ".jsx",
  ".kt",
  ".lock",
  ".md",
  ".php",
  ".png",
  ".py",
  ".rb",
  ".rs",
  ".scss",
  ".sh",
  ".sql",
  ".svg",
  ".swift",
  ".toml",
  ".ts",
  ".tsx",
  ".txt",
  ".webp",
  ".xml",
  ".yaml",
  ".yml",
  ".zsh",
])

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

function pathWithoutFragment(value: string) {
  return value.split("#", 1)[0].split("?", 1)[0]
}

function hasKnownFileExtension(value: string) {
  const fileName = basename(value)
  if (FILE_REFERENCE_EXTENSIONS.has(fileName.toLowerCase())) return true
  return FILE_REFERENCE_EXTENSIONS.has(extname(fileName).toLowerCase())
}

function resolvablePath(value: string, directory: string) {
  if (!directory) return false
  const path = pathWithoutFragment(value).replace(/^~(?=\/)/, process.env.HOME ?? "~")
  const candidate = isAbsolute(path) ? path : join(directory, path)
  return existsSync(normalize(candidate))
}

function isFileLikeReference(value: string, directory: string) {
  const path = value.split("#", 1)[0].split("?", 1)[0]
  if (resolvablePath(path, directory)) return true
  return (
    hasKnownFileExtension(path) ||
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
    if (!isFileLikeReference(reference, input.directory)) continue
    const start = match.index ?? 0
    const value = `@${reference}`
    const url = fileAutocompleteURL({
      baseDirectory: input.directory,
      item: reference,
    })
    const pathKey = `path:${reference}`
    const urlKey = `url:${url}`
    if (seen.has(pathKey) || seen.has(urlKey) || existing.has(pathKey) || existing.has(urlKey)) continue
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
