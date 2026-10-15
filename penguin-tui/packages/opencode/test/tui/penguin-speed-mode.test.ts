import { describe, expect, test } from "bun:test"
import {
  createPenguinSpeedModes,
  isPenguinSpeedPreference,
  type PenguinSpeedPreference,
} from "../../src/cli/cmd/tui/context/penguin-speed-mode"
import { applyPenguinFastCommand } from "../../src/cli/cmd/tui/component/prompt/penguin-fast-command"

function modes(initial: PenguinSpeedPreference = undefined, configured?: string) {
  let value = initial
  const controller = createPenguinSpeedModes({
    get: () => value,
    set: (next) => {
      value = next
    },
    configured: () => configured,
  })
  return { ...controller, value: () => value }
}

describe("Penguin ultrafast mode", () => {
  test("inherits configuration without sending an override", () => {
    const speed = modes(undefined, " ULTRAFAST ")
    expect(speed.ultrafast.enabled()).toBe(true)
    expect(speed.fast.enabled()).toBe(false)
    expect(speed.fast.serviceTier()).toBeUndefined()
    speed.ultrafast.toggle()
    expect(speed.fast.serviceTier()).toBe("default")
    speed.ultrafast.set(undefined)
    expect(speed.ultrafast.enabled()).toBe(true)
  })

  test("preserves legacy preferences and round-trips ultrafast", () => {
    for (const preference of [true, false, "ultrafast"] as const) {
      const restored: unknown = JSON.parse(JSON.stringify({ fast: preference })).fast
      expect(isPenguinSpeedPreference(restored)).toBe(true)
      if (!isPenguinSpeedPreference(restored)) throw new Error("Invalid preference")
      const speed = modes(restored)
      expect(speed.fast.serviceTier()).toBe(
        preference === true ? "priority" : preference === false ? "default" : "ultrafast",
      )
    }
    expect(isPenguinSpeedPreference("turbo")).toBe(false)
    expect(isPenguinSpeedPreference(null)).toBe(false)
  })

  test("toggles ultrafast and switches exclusively between modes", () => {
    const speed = modes(true)
    expect(applyPenguinFastCommand({ ...speed, text: "/ultrafast" })).toEqual({
      matched: true,
      message: "Ultrafast mode on",
      variant: "info",
    })
    expect(speed.fast.enabled()).toBe(false)
    expect(speed.fast.serviceTier()).toBe("ultrafast")
    expect(applyPenguinFastCommand({ ...speed, text: "/ultrafast status" })).toMatchObject({
      message: "Ultrafast mode on",
    })
    expect(speed.value()).toBe("ultrafast")
    applyPenguinFastCommand({ ...speed, text: "/fast on" })
    expect(speed.ultrafast.enabled()).toBe(false)
    expect(speed.fast.serviceTier()).toBe("priority")
    applyPenguinFastCommand({ ...speed, text: "/ultrafast ON" })
    expect(speed.fast.serviceTier()).toBe("ultrafast")
    applyPenguinFastCommand({ ...speed, text: "/ultrafast off" })
    expect(speed.fast.serviceTier()).toBe("default")
    applyPenguinFastCommand({ ...speed, text: "/ultrafast" })
    applyPenguinFastCommand({ ...speed, text: "/ultrafast" })
    expect(speed.fast.serviceTier()).toBe("default")
  })

  test("invalid arguments do not change the mode", () => {
    const speed = modes("ultrafast")
    for (const text of ["/ultrafast turbo", "/ultrafast on extra", "/fast off extra"]) {
      expect(applyPenguinFastCommand({ ...speed, text })).toMatchObject({ matched: true, variant: "warning" })
      expect(speed.fast.serviceTier()).toBe("ultrafast")
    }
    expect(applyPenguinFastCommand({ ...speed, text: "hello" })).toEqual({ matched: false })
  })
})
