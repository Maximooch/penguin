function readPenguinEnv(name: string): string | undefined {
  const candidates = [
    process.env[name],
    typeof Bun !== "undefined" ? Bun.env?.[name] : undefined,
  ]

  for (const candidate of candidates) {
    if (typeof candidate !== "string") continue
    const normalized = candidate.trim()
    if (normalized) return normalized
  }

  return undefined
}

export function getPenguinAuthHeaders(): Record<string, string> | undefined {
  const token =
    readPenguinEnv("PENGUIN_LOCAL_AUTH_TOKEN") ??
    readPenguinEnv("PENGUIN_AUTH_STARTUP_TOKEN")
  if (!token) return
  return { "X-API-Key": token }
}
