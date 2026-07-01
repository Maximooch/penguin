import { describe, expect, test } from "bun:test"
import { Flag } from "../../src/flag/flag"
import { createServerAuthorizationHeader, createServerFetchRequest } from "../../src/server/auth-header"

function withServerPassword<T>(password: string | undefined, fn: () => T): T {
  const previous = Object.getOwnPropertyDescriptor(Flag, "OPENCODE_SERVER_PASSWORD")
  Object.defineProperty(Flag, "OPENCODE_SERVER_PASSWORD", {
    configurable: true,
    enumerable: true,
    value: password,
  })
  try {
    return fn()
  } finally {
    if (previous) Object.defineProperty(Flag, "OPENCODE_SERVER_PASSWORD", previous)
  }
}

describe("server auth header", () => {
  test("omits authorization when no password is configured", () => {
    withServerPassword(undefined, () => {
      expect(createServerAuthorizationHeader({})).toBeUndefined()
    })
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
    const request = withServerPassword(undefined, () =>
      createServerFetchRequest("http://opencode.internal/session", { headers: { "X-Test": "yes" } }),
    )

    expect(request.headers.get("Authorization")).toBeNull()
    expect(request.headers.get("X-Test")).toBe("yes")
  })

  test("preserves caller-supplied authorization headers", () => {
    const request = createServerFetchRequest(
      "http://opencode.internal/session",
      {
        headers: {
          Authorization: "Bearer caller",
        },
      },
      "Basic server",
    )

    expect(request.headers.get("Authorization")).toBe("Bearer caller")
  })
})
