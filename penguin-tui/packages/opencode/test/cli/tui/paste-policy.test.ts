import { describe, expect, test } from "bun:test"
import {
  createPasteDuplicateGuard,
  normalizePastedText,
  shouldSummarizePaste,
} from "../../../src/cli/cmd/tui/component/prompt/paste-policy"

describe("prompt paste policy", () => {
  test("normalizes terminal paste line endings", () => {
    expect(normalizePastedText("one\r\ntwo\rthree")).toBe("one\ntwo\nthree")
  })

  test("summarizes long or multiline paste unless disabled", () => {
    expect(shouldSummarizePaste("one\ntwo\nthree")).toBe(true)
    expect(shouldSummarizePaste("x".repeat(151))).toBe(true)
    expect(shouldSummarizePaste("one\ntwo\nthree", true)).toBe(false)
    expect(shouldSummarizePaste("short text")).toBe(false)
  })

  test("drops only immediate duplicate paste events", () => {
    let now = 1000
    const guard = createPasteDuplicateGuard({
      now: () => now,
      windowMs: 100,
    })

    expect(guard.shouldDrop("hello")).toBe(false)
    now += 20
    expect(guard.shouldDrop("hello")).toBe(true)
    now += 20
    expect(guard.shouldDrop("hello!")).toBe(false)
    now += 150
    expect(guard.shouldDrop("hello!")).toBe(false)
  })
})
