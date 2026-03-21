export function apiErrorMessage(error: unknown, fallback = "Request failed") {
  if (!error) return fallback
  if (typeof error === "string") return error
  if (error instanceof Error && error.message) return error.message
  if (typeof error !== "object") return fallback

  const entry = error as Record<string, unknown>
  if (typeof entry.message === "string" && entry.message.trim()) {
    return entry.message.trim()
  }

  const data = entry.data
  if (!data || typeof data !== "object") return fallback
  const payload = data as Record<string, unknown>

  if (typeof payload.detail === "string" && payload.detail.trim()) {
    return payload.detail.trim()
  }

  if (typeof payload.message === "string" && payload.message.trim()) {
    return payload.message.trim()
  }

  if (!Array.isArray(payload.errors) || payload.errors.length === 0) {
    return fallback
  }

  const first = payload.errors[0]
  if (typeof first === "string" && first.trim()) return first.trim()
  if (!first || typeof first !== "object") return fallback

  const detail = first as Record<string, unknown>
  if (typeof detail.message === "string" && detail.message.trim()) {
    return detail.message.trim()
  }
  if (typeof detail.detail === "string" && detail.detail.trim()) {
    return detail.detail.trim()
  }

  return fallback
}
