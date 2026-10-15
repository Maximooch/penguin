import { describe, expect, test } from "bun:test"
import { createProgramStatus } from "../../../src/cli/cmd/tui/program-status"

const idle = {
  sessionID: "session-1",
  busy: false,
  permission: false,
  question: false,
  connection: "connected" as const,
}

function terminal(options: { enabled?: boolean; tmux?: boolean } = {}) {
  const output: string[] = []
  const status = createProgramStatus({ enabled: true, ...options, write: (value) => output.push(value) })
  return { output, status }
}

function last(output: string[]) {
  return output.at(-1) ?? ""
}

describe("OSC 7501 program status", () => {
  test("reports transitions once, encodes messages, and acknowledges completion", () => {
    const { status, output } = terminal()
    status.update(idle)
    expect(last(output)).toBe("\x1b]7501;state=idle:app=penguin:msg=V2FpdGluZyBmb3IgYSBwcm9tcHQ=\x1b\\")
    status.update(idle)
    expect(output).toHaveLength(1)
    status.update({ ...idle, busy: true })
    expect(last(output)).toContain("state=working:")
    status.update(idle)
    expect(last(output)).toContain("state=done:")
    status.update(idle)
    expect(output).toHaveLength(3)
    status.acknowledge()
    expect(last(output)).toContain("state=idle:")
  })

  test("pending approvals and questions take priority over busy and idle events", () => {
    const { status, output } = terminal()
    status.update({ ...idle, busy: true })
    status.update({ ...idle, busy: true, permission: true, question: true })
    expect(last(output)).toContain("state=blocked:app=penguin:kind=permission:")
    status.update({ ...idle, permission: true, question: true })
    expect(last(output)).toContain("kind=permission:")
    status.update({ ...idle, question: true })
    expect(last(output)).toContain("kind=question:")
    status.update({ ...idle, busy: true })
    expect(last(output)).toContain("state=working:")
    status.update(idle)
    expect(last(output)).toContain("state=done:")
  })

  test("cancellation stays idle through late messages until another run starts", () => {
    const { status, output } = terminal()
    status.update({ ...idle, busy: true })
    status.interrupt("another-session")
    expect(last(output)).toContain("state=working:")
    status.interrupt(idle.sessionID)
    status.update({ ...idle, busy: true, question: true })
    status.update(idle)
    status.fail(idle.sessionID)
    expect(last(output)).toContain("state=idle:")
    expect(output.some((value) => value.includes("state=done:"))).toBe(false)
    status.update({ ...idle, busy: true })
    expect(last(output)).toContain("state=working:")
  })

  test("errors survive following idle events and acknowledgements cannot turn them into success", () => {
    const { status, output } = terminal()
    status.update({ ...idle, busy: true })
    status.update({ ...idle, busy: true, errorID: "failed-message" })
    expect(last(output)).toContain("state=error:")
    status.acknowledge()
    status.update({ ...idle, errorID: "failed-message" })
    expect(last(output)).toContain("state=idle:")
    expect(output.some((value) => value.includes("state=done:"))).toBe(false)
    status.update({ ...idle, busy: true, errorID: "failed-message" })
    expect(last(output)).toContain("state=working:")
    status.fail(idle.sessionID)
    status.update({ ...idle, errorID: "failed-message" })
    expect(last(output)).toContain("state=error:")
  })

  test("reconnection reports activity and authentication failures request user action", () => {
    const { status, output } = terminal()
    status.update({ ...idle, connection: "reconnecting" })
    expect(last(output)).toContain("state=working:")
    status.update({ ...idle, connection: "denied" })
    expect(last(output)).toContain("state=blocked:app=penguin:kind=auth:")
    status.update(idle)
    expect(last(output)).toContain("state=idle:")
  })

  test("changing sessions discards the previous outcome and historical errors", () => {
    const { status, output } = terminal()
    status.update({ ...idle, busy: true })
    status.update({ ...idle, sessionID: "session-2", errorID: "old-error" })
    expect(last(output)).toContain("state=idle:")
    status.fail("session-1")
    expect(last(output)).toContain("state=idle:")
    status.update({ ...idle, sessionID: undefined })
    expect(last(output)).toContain("state=idle:")
  })

  test("shutdown clears live activity but preserves unacknowledged results", () => {
    for (const result of ["working", "blocked", "done", "error"] as const) {
      const { status, output } = terminal()
      status.update({ ...idle, busy: true })
      if (result === "blocked") status.update({ ...idle, busy: true, permission: true })
      if (result === "done") status.update(idle)
      if (result === "error") status.fail(idle.sessionID)
      status.dispose()
      expect(last(output)).toContain(`state=${result === "done" || result === "error" ? result : "idle"}:`)
    }
  })

  test("does not emit when disabled and escapes both ESC bytes for tmux", () => {
    const disabled = terminal({ enabled: false })
    disabled.status.update(idle)
    disabled.status.fail(idle.sessionID)
    disabled.status.dispose()
    expect(disabled.output).toEqual([])
    const mux = terminal({ tmux: true })
    mux.status.update(idle)
    expect(last(mux.output)).toBe(
      "\x1bPtmux;\x1b\x1b]7501;state=idle:app=penguin:msg=V2FpdGluZyBmb3IgYSBwcm9tcHQ=\x1b\x1b\\\x1b\\",
    )
  })
})
