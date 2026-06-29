import { describe, expect, test } from "bun:test"
import {
  createPasteDuplicateGuard,
  normalizePastedText,
  removePastedPathReferences,
  shouldOwnPasteEvent,
  shouldSummarizePaste,
} from "../../../src/cli/cmd/tui/component/prompt/paste-policy"

describe("prompt paste policy", () => {
  test("normalizes terminal paste line endings", () => {
    expect(normalizePastedText("one\r\ntwo\rthree")).toBe("one\ntwo\nthree")
  })

  test("summarizes long or multiline paste unless disabled", () => {
    expect(shouldSummarizePaste("one\ntwo\nthree")).toBe(true)
    expect(shouldSummarizePaste("one\rtwo\rthree")).toBe(true)
    expect(shouldSummarizePaste("x".repeat(151))).toBe(true)
    expect(shouldSummarizePaste("one\ntwo\nthree", true)).toBe(false)
    expect(shouldSummarizePaste("short text")).toBe(false)
  })

  test("removes pasted path references while preserving surrounding text", () => {
    expect(
      removePastedPathReferences("see /tmp/example diagram.svg please", [
        "/tmp/example diagram.svg",
        "/tmp/example\\ diagram.svg",
      ]),
    ).toBe("see please")
  })

  test("claims non-empty paste events before async probing", () => {
    expect(shouldOwnPasteEvent("short text")).toBe(true)
    expect(shouldOwnPasteEvent("one\r\ntwo")).toBe(true)
    expect(shouldOwnPasteEvent("")).toBe(false)
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
