import { Log } from "@/util/log"

type BootstrapFetch = (input: string | URL, init?: RequestInit) => Promise<Response>

export async function fetchBootstrapJson<T>(input: {
  fetch: BootstrapFetch
  path: string | URL
  endpoint: string
  fallback: T
  required?: boolean
}): Promise<T> {
  try {
    const res = await input.fetch(input.path)
    if (res.ok) {
      return res.json().catch(() => input.fallback)
    }

    const details = await res.text().catch(() => "")
    const error = new Error(
      details
        ? `Bootstrap request failed (${res.status}): ${details}`
        : `Bootstrap request failed (${res.status})`,
    )
    if (input.required) throw error
    Log.Default.warn("penguin bootstrap degraded", {
      endpoint: input.endpoint,
      status: res.status,
      details: details || undefined,
    })
    return input.fallback
  } catch (error) {
    if (input.required) throw error
    Log.Default.warn("penguin bootstrap degraded", {
      endpoint: input.endpoint,
      error: error instanceof Error ? error.message : String(error),
    })
    return input.fallback
  }
}
