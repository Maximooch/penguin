const DISABLED_VALUES = new Set(["0", "false", "no", "off"])

export function shouldUseOpenCodeMarkdownRenderer(
  value = process.env.OPENCODE_EXPERIMENTAL_MARKDOWN,
): boolean {
  if (typeof value !== "string") return true
  return !DISABLED_VALUES.has(value.trim().toLowerCase())
}
