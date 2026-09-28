import { describe, expect, test } from "bun:test"
import { createSessionAccessClient, type AccessMode } from "../../src/cli/cmd/tui/context/session-access"

describe("session access client", () => {
  test("loads and changes session modes through the backend", async () => {
    const modes = new Map<string, AccessMode>()
    const server = Bun.serve({
      port: 0,
      hostname: "127.0.0.1",
      async fetch(request) {
        const session = decodeURIComponent(new URL(request.url).pathname.split("/").at(-2)!)
        if (request.method === "PUT") {
          expect(request.headers.get("content-type")).toBe("application/json")
          const body = await request.json()
          modes.set(session, body.mode)
        }
        return Response.json({ session_id: session, mode: modes.get(session) ?? "workspace" })
      },
    })
    try {
      const client = createSessionAccessClient(server.url.toString(), fetch)
      expect(await client.load("session-one")).toBe("workspace")
      expect(await client.set("session-one", "full_access")).toBe("full_access")
      expect(client.get("session-one")).toBe("full_access")
      expect(await client.load("session-two")).toBe("workspace")
      expect(client.get("session-one")).toBe("full_access")
      expect(await client.set("session-one", "workspace")).toBe("workspace")
    } finally {
      server.stop(true)
    }
  })

  test.each(["denied", "wrong-session", "invalid-mode"])("does not display unconfirmed access: %s", async (failure) => {
    const server = Bun.serve({
      port: 0,
      hostname: "127.0.0.1",
      fetch(request) {
        if (request.method === "GET") return Response.json({ session_id: "one", mode: "workspace" })
        if (failure === "denied") return new Response("Forbidden", { status: 403 })
        return Response.json({
          session_id: failure === "wrong-session" ? "two" : "one",
          mode: failure === "invalid-mode" ? "invalid" : "full_access",
        })
      },
    })
    try {
      const client = createSessionAccessClient(server.url.toString(), fetch)
      await client.load("one")
      await expect(client.set("one", "full_access")).rejects.toThrow()
      expect(client.get("one")).toBe("workspace")
    } finally {
      server.stop(true)
    }
  })
})
