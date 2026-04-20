import { afterEach, beforeEach, describe, expect, spyOn, test } from "bun:test"
import { fetchBootstrapJson } from "../../../src/cli/cmd/tui/context/sync-bootstrap"
import { Log } from "../../../src/util/log"

describe("sync bootstrap", () => {
  let warn: ReturnType<typeof spyOn>

  beforeEach(() => {
    warn = spyOn(Log.Default, "warn").mockImplementation(() => {})
  })

  afterEach(() => {
    warn.mockRestore()
  })

  test("returns parsed bootstrap json on success", async () => {
    const result = await fetchBootstrapJson({
      fetch: async () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
      path: "http://localhost/config",
      endpoint: "/config",
      fallback: undefined as { ok: boolean } | undefined,
    })

    expect(result).toEqual({ ok: true })
    expect(warn).not.toHaveBeenCalled()
  })

  test("degrades to fallback on non-2xx bootstrap response", async () => {
    const fallback = { share: "disabled" }
    const result = await fetchBootstrapJson({
      fetch: async () => new Response("unauthorized", { status: 401 }),
      path: "http://localhost/config",
      endpoint: "/config",
      fallback,
    })

    expect(result).toBe(fallback)
    expect(warn).toHaveBeenCalledTimes(1)
  })

  test("throws for required bootstrap failures", async () => {
    await expect(
      fetchBootstrapJson({
        fetch: async () => {
          throw new Error("network down")
        },
        path: "http://localhost/config",
        endpoint: "/config",
        fallback: undefined,
        required: true,
      }),
    ).rejects.toThrow("network down")

    expect(warn).not.toHaveBeenCalled()
  })
})
