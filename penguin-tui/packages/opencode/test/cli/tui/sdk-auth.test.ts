import { afterEach, describe, expect, test } from "bun:test"
import { getPenguinAuthHeaders } from "../../../src/cli/cmd/tui/context/penguin-auth"

const ORIGINAL_LOCAL_AUTH_TOKEN = process.env.PENGUIN_LOCAL_AUTH_TOKEN
const ORIGINAL_STARTUP_TOKEN = process.env.PENGUIN_AUTH_STARTUP_TOKEN

function restoreEnv() {
  if (ORIGINAL_LOCAL_AUTH_TOKEN === undefined) {
    delete process.env.PENGUIN_LOCAL_AUTH_TOKEN
  } else {
    process.env.PENGUIN_LOCAL_AUTH_TOKEN = ORIGINAL_LOCAL_AUTH_TOKEN
  }

  if (ORIGINAL_STARTUP_TOKEN === undefined) {
    delete process.env.PENGUIN_AUTH_STARTUP_TOKEN
  } else {
    process.env.PENGUIN_AUTH_STARTUP_TOKEN = ORIGINAL_STARTUP_TOKEN
  }
}

afterEach(() => {
  restoreEnv()
})

describe("penguin auth headers", () => {
  test("uses the local auth token when present", () => {
    process.env.PENGUIN_LOCAL_AUTH_TOKEN = "local-token"
    process.env.PENGUIN_AUTH_STARTUP_TOKEN = "startup-token"

    expect(getPenguinAuthHeaders()).toEqual({ "X-API-Key": "local-token" })
  })

  test("falls back to the startup token when the local token is blank", () => {
    process.env.PENGUIN_LOCAL_AUTH_TOKEN = "   "
    process.env.PENGUIN_AUTH_STARTUP_TOKEN = "startup-token"

    expect(getPenguinAuthHeaders()).toEqual({ "X-API-Key": "startup-token" })
  })

  test("returns undefined when both auth tokens are blank", () => {
    process.env.PENGUIN_LOCAL_AUTH_TOKEN = ""
    process.env.PENGUIN_AUTH_STARTUP_TOKEN = " "

    expect(getPenguinAuthHeaders()).toBeUndefined()
  })
})
