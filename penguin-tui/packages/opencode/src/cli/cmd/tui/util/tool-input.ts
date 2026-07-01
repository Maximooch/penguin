export type ToolInputRecord = Record<string, unknown>

export function isToolInputRecord(value: unknown): value is ToolInputRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

export function coerceToolInputRecord(value: unknown): ToolInputRecord {
  if (isToolInputRecord(value)) return value
  if (value === undefined || value === null) return {}
  return { value }
}

export function formatPrimitiveToolInput(value: unknown, omit: readonly string[] = []): string {
  const input = coerceToolInputRecord(value)
  const primitives = Object.entries(input).filter(([key, item]) => {
    if (omit.includes(key)) return false
    return typeof item === "string" || typeof item === "number" || typeof item === "boolean"
  })
  if (primitives.length === 0) return ""
  return `[${primitives.map(([key, item]) => `${key}=${item}`).join(", ")}]`
}

export function stringifyToolInput(value: unknown, space = 2): string {
  const path: object[] = []
  const result = JSON.stringify(
    value,
    function replacer(this: unknown, _key, item) {
      if (typeof item === "bigint") return item.toString()
      if (typeof item === "function") return item.name ? `[Function ${item.name}]` : "[Function]"
      if (typeof item === "symbol") return item.toString()
      if (typeof item !== "object" || item === null) return item

      while (path.length > 0 && path.at(-1) !== this) {
        path.pop()
      }
      if (path.includes(item)) return "[Circular]"
      path.push(item)
      return item
    },
    space,
  )
  return result ?? String(value)
}
