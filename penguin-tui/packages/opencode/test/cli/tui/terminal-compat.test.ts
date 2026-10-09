import { expect, test } from "bun:test"
import { createProgramStatus } from "../../../src/cli/cmd/tui/program-status"
import {
  notificationEscape,
  notifyForProgramStatus,
  terminalNotificationIdentity,
} from "../../../src/cli/cmd/tui/notification-runtime"
import { terminalNotificationProtocol, terminalProgramTitle } from "../../../src/cli/cmd/tui/terminal-compat"

test("chooses compatible protocols, detecting cmux before its host terminal", () => {
  for (const [env, expected] of [
    [{ TERM_PROGRAM: "Apple_Terminal" }, "bell"],
    [{}, "bell"],
    [{ TERM_PROGRAM: "ghostty", CMUX_WORKSPACE_ID: "test" }, "osc777"],
    [{ TERM_PROGRAM: "WezTerm" }, "osc777"],
    [{ TERM_PROGRAM: "iTerm.app" }, "osc9"],
    [{ TERM_PROGRAM: "ghostty" }, "osc9"],
    [{ TERM: "xterm-kitty" }, "osc99"],
    [{ TERM_PROGRAM: "cmux", PENGUIN_TUI_NOTIFICATION_PROTOCOL: "bell" }, "bell"],
  ] as const)
    expect(terminalNotificationProtocol(env)).toBe(expected)
  expect(terminalNotificationIdentity({ TERM_PROGRAM: "ghostty", CMUX_WORKSPACE_ID: "test" }).app).toBe("CMUX")
})

test("emits native Terminal bells, cmux notifications, Kitty notifications and tmux passthrough", () => {
  const payload = { channel: "terminal" as const, category: "run_complete" as const, title: "Penguin", body: "Done" }
  expect(notificationEscape(payload, { TERM_PROGRAM: "Apple_Terminal" })).toBe("\x07")
  expect(notificationEscape(payload, { CMUX_WORKSPACE_ID: "test" })).toBe("\x1b]777;notify;Penguin;Done\x07")
  expect(notificationEscape(payload, { TERM_PROGRAM: "kitty" })).toBe(
    "\x1b]99;p=title:d=0;Penguin\x1b\\\x1b]99;p=body:d=1;Done\x1b\\",
  )
  expect(notificationEscape(payload, { CMUX_WORKSPACE_ID: "test", TMUX: "1" })).toBe(
    "\x1bPtmux;\x1b\x1b]777;notify;Penguin;Done\x07\x1b\\",
  )
  expect(notificationEscape(payload, { TERM_PROGRAM: "Apple_Terminal", TMUX: "1" })).toBe("\x07")
})

test("shares outcomes between titles and notifications without false completion after abort or error", () => {
  const titles: string[] = []
  const categories: string[] = []
  const idle = { sessionID: "test", busy: false, permission: false, question: false, connection: "connected" as const }
  const status = createProgramStatus({
    enabled: false,
    write: () => {
      throw new Error("disabled OSC writer")
    },
    onChange: (report) => {
      titles.push(terminalProgramTitle(report, "Penguin"))
      categories.push(
        ...notifyForProgramStatus(report, "test", { mode: "bell" }, { write: () => {} }).map((x) => x.category),
      )
    },
  })
  status.update(idle)
  status.update({ ...idle, busy: true })
  status.interrupt("test")
  status.update(idle)
  expect(categories).toEqual([])
  status.update({ ...idle, busy: true })
  status.fail("test")
  status.update(idle)
  expect(categories).toEqual(["run_failed"])
  status.update({ ...idle, busy: true })
  status.update({ ...idle, busy: true, permission: true })
  status.update({ ...idle, busy: true })
  status.update(idle)
  expect(categories).toEqual(["run_failed", "approval_waiting", "run_complete"])
  expect(titles).toContain("[Needs input] Penguin")
  expect(titles.at(-1)).toBe("[Done] Penguin")
  expect(terminalProgramTitle({ state: "idle", message: "" }, "Penguin\x1b]2;bad")).toBe("[Idle] Penguin ]2;bad")
  expect(notifyForProgramStatus({ state: "done", message: "Run complete" }, "test", { mode: "off" })).toEqual([])
})
