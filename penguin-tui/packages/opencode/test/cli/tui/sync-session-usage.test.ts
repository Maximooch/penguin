import { describe, expect, test } from "bun:test"
import { createPenguinSessionUsageUrl } from "../../../src/cli/cmd/tui/context/sync-session-usage"

describe("Penguin session usage sync", () => {
  test("uses the session-specific token usage route", () => {
    const url = createPenguinSessionUsageUrl("http://127.0.0.1:9000", "session_123")

    expect(url.toString()).toBe("http://127.0.0.1:9000/api/v1/sessions/session_123/token-usage")
  })

  test("encodes session ids in the route path", () => {
    const url = createPenguinSessionUsageUrl("http://127.0.0.1:9000", "session with/slash")

    expect(url.pathname).toBe("/api/v1/sessions/session%20with%2Fslash/token-usage")
    expect(url.search).toBe("")
  })
})
