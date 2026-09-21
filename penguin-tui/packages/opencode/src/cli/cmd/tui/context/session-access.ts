import { createStore } from "solid-js/store"

export type AccessMode = "workspace" | "full_access"

export function createSessionAccessClient(url: string, request: typeof fetch) {
  const [modes, setModes] = createStore<Record<string, AccessMode>>({})

  async function sync(sessionID: string, mode?: AccessMode) {
    const response = await request(new URL(`/api/v1/session/${encodeURIComponent(sessionID)}/access`, url), {
      method: mode ? "PUT" : "GET",
      headers: mode ? { "Content-Type": "application/json" } : undefined,
      body: mode ? JSON.stringify({ mode }) : undefined,
    })
    if (!response.ok) throw new Error(`Could not load or update permissions (HTTP ${response.status})`)
    const data = await response.json()
    if (!data || data.session_id !== sessionID || (data.mode !== "workspace" && data.mode !== "full_access")) {
      throw new Error("Invalid session permissions response")
    }
    setModes(sessionID, data.mode)
    return data.mode as AccessMode
  }

  return {
    get: (sessionID: string) => modes[sessionID],
    load: (sessionID: string) => sync(sessionID),
    set: (sessionID: string, mode: AccessMode) => sync(sessionID, mode),
  }
}
