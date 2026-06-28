import { describe, expect, test } from "bun:test"
import { createServerAuthorizationHeader, createServerFetchRequest } from "../../src/server/auth-header"

describe("server auth header", () => {
  test("omits authorization when no password is configured", () => {
    expect(createServerAuthorizationHeader({})).toBeUndefined()
  })

  test("creates a basic authorization header", () => {
    expect(createServerAuthorizationHeader({ username: "penguin", password: "secret" })).toBe(
      `Basic ${btoa("penguin:secret")}`,
    )
  })

  test("injects authorization into in-process fetch requests", () => {
    const request = createServerFetchRequest(
      "http://opencode.internal/session",
      {
        method: "POST",
        headers: { "X-Test": "yes" },
        body: "payload",
      },
      "Basic token",
    )

    expect(request.method).toBe("POST")
    expect(request.headers.get("Authorization")).toBe("Basic token")
    expect(request.headers.get("X-Test")).toBe("yes")
  })

  test("preserves requests without authorization", () => {
    const request = createServerFetchRequest("http://opencode.internal/session", { headers: { "X-Test": "yes" } })

    expect(request.headers.get("Authorization")).toBeNull()
    expect(request.headers.get("X-Test")).toBe("yes")
  })
})
