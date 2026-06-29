import { describe, expect, test } from "bun:test"

import {
  attentionEventFromSyncEvent,
  deliverNotificationPayloads,
  notificationCommand,
  notificationEscape,
  notificationEventKey,
  notifyForSyncEvent,
  shouldSuppressNotificationForActiveSession,
  terminalNotificationIdentity,
} from "../../../src/cli/cmd/tui/notification-runtime"

describe("terminal notification runtime", () => {
  test("maps approval and question events into attention events", () => {
    expect(
      attentionEventFromSyncEvent({
        type: "permission.asked",
        properties: {
          id: "perm_1",
          sessionID: "ses_1",
          title: "Run shell command",
        },
      }),
    ).toEqual({
      category: "approval_waiting",
      sessionID: "ses_1",
      title: "Penguin needs approval",
      message: "Run shell command",
    })

    expect(
      attentionEventFromSyncEvent({
        type: "question.asked",
        properties: {
          id: "question_1",
          sessionID: "ses_2",
          question: "Continue?",
        },
      }),
    ).toEqual({
      category: "question_waiting",
      sessionID: "ses_2",
      title: "Penguin has a question",
      message: "Continue?",
    })
  })

  test("builds stable duplicate-suppression keys", () => {
    expect(
      notificationEventKey({
        type: "permission.asked",
        properties: {
          id: "perm_1",
          sessionID: "ses_1",
        },
      }),
    ).toBe("permission.asked:ses_1:perm_1")

    expect(
      notificationEventKey({
        type: "session.status",
        properties: {
          messageID: "msg_1",
          sessionID: "ses_1",
          status: {
            type: "idle",
          },
        },
      }),
    ).toBe("session.status:ses_1:msg_1")

    expect(
      notificationEventKey({
        type: "session.status",
        properties: {
          sessionID: "ses_1",
          status: {
            type: "busy",
          },
        },
      }),
    ).toBeUndefined()
  })

  test("suppresses attention notifications for the active session", () => {
    expect(
      shouldSuppressNotificationForActiveSession(
        {
          type: "question.asked",
          properties: {
            id: "question_1",
            sessionID: "ses_active",
            question: "Continue?",
          },
        },
        {
          activeSessionID: "ses_active",
          terminalFocused: true,
        },
      ),
    ).toBe(true)

    expect(
      shouldSuppressNotificationForActiveSession(
        {
          type: "session.status",
          properties: {
            messageID: "msg_1",
            sessionID: "ses_active",
            status: {
              type: "idle",
            },
          },
        },
        {
          activeSessionID: "ses_active",
          terminalFocused: true,
        },
      ),
    ).toBe(true)
  })

  test("keeps background, blurred, and non-attention events eligible for normal handling", () => {
    expect(
      shouldSuppressNotificationForActiveSession(
        {
          type: "question.asked",
          properties: {
            id: "question_1",
            sessionID: "ses_background",
            question: "Continue?",
          },
        },
        {
          activeSessionID: "ses_active",
          terminalFocused: true,
        },
      ),
    ).toBe(false)

    expect(
      shouldSuppressNotificationForActiveSession(
        {
          type: "question.asked",
          properties: {
            id: "question_1",
            sessionID: "ses_active",
            question: "Continue?",
          },
        },
        {
          activeSessionID: "ses_active",
          terminalFocused: false,
        },
      ),
    ).toBe(false)

    expect(
      shouldSuppressNotificationForActiveSession(
        {
          type: "message.updated",
          properties: {
            sessionID: "ses_active",
          },
        },
        {
          activeSessionID: "ses_active",
          terminalFocused: true,
        },
      ),
    ).toBe(false)
  })

  test("delivers terminal bell and logs every notification attempt", () => {
    const writes: string[] = []
    const logs: string[] = []

    const delivered = deliverNotificationPayloads(
      [
        {
          channel: "bell",
          category: "approval_waiting",
          title: "Penguin needs approval",
          body: "Approve?",
        },
        {
          channel: "visual",
          category: "question_waiting",
          title: "Penguin has a question",
          body: "Continue?",
        },
      ],
      {
        write: (text) => writes.push(text),
        log: (payload) => logs.push(payload.title),
      },
    )

    expect(delivered).toHaveLength(2)
    expect(writes).toEqual(["\u0007"])
    expect(logs).toEqual(["Penguin needs approval", "Penguin has a question"])
  })

  test("sanitizes OSC notification separators", () => {
    expect(
      notificationEscape({
        channel: "osc",
        category: "run_failed",
        title: "Bad;title\u0007",
        body: "Bad;body\u0007",
      }),
    ).toBe("\u001b]9;Bad title ;Bad body \u0007")
  })

  test("builds terminal notification escape payloads", () => {
    expect(
      notificationEscape({
        channel: "terminal",
        category: "question_waiting",
        title: "Bad;title\u0007",
        body: "Bad;body\u0007",
      }),
    ).toBe("\u001b]9;Bad title ;Bad body \u0007")
  })

  test("builds macOS desktop and audio commands without shell interpolation", () => {
    expect(
      notificationCommand(
        {
          channel: "sound",
          category: "run_complete",
          title: "Penguin run complete",
          body: "Finished",
          sound: "noot-noot",
        },
        "darwin",
      ),
    ).toEqual(["/usr/bin/say", "NOOT NOOT"])

    expect(
      notificationCommand(
        {
          channel: "sound",
          category: "tool_complete",
          title: "Tool finished",
          body: "Finished",
          sound: "arrival",
        },
        "darwin",
      ),
    ).toEqual(["/usr/bin/afplay", "/System/Library/Sounds/Ping.aiff"])

    expect(
      notificationCommand(
        {
          channel: "os",
          category: "question_waiting",
          title: 'Penguin "needs" approval',
          body: "Approve; this?",
          sound: "boarding-call",
        },
        "darwin",
      ),
    ).toEqual([
      "/usr/bin/osascript",
      "-e",
      'display notification "Approve; this?" with title "Penguin \\"needs\\" approval" sound name "Glass"',
    ])
  })

  test("uses terminal-notifier sender identity for macOS terminal app icons when available", () => {
    expect(
      notificationCommand(
        {
          channel: "os",
          category: "run_complete",
          title: "Penguin run complete",
          body: "Finished",
        },
        "darwin",
        {
          terminalBundleID: "com.mitchellh.ghostty",
          terminalNotifier: "/usr/local/bin/terminal-notifier",
        },
      ),
    ).toEqual([
      "/usr/local/bin/terminal-notifier",
      "-title",
      "Penguin run complete",
      "-message",
      "Finished",
      "-sender",
      "com.mitchellh.ghostty",
    ])
  })

  test("resolves terminal notification identity for CMUX and common macOS terminals", () => {
    expect(terminalNotificationIdentity({ TERM_PROGRAM: "cmux" })).toEqual({
      app: "CMUX",
      bundleID: "com.cmuxterm.app",
    })

    expect(terminalNotificationIdentity({ CMUX: "1" })).toEqual({
      app: "CMUX",
      bundleID: "com.cmuxterm.app",
    })

    expect(terminalNotificationIdentity({ TERM_PROGRAM: "Ghostty" })).toEqual({
      app: "Ghostty",
      bundleID: "com.mitchellh.ghostty",
    })

    expect(terminalNotificationIdentity({ TERM_PROGRAM: "Apple_Terminal", TMUX: "/tmp/tmux" })).toEqual({
      app: "Apple Terminal via tmux",
      bundleID: "com.apple.Terminal",
    })
  })

  test("targets the terminal app bundle with the AppleScript fallback", () => {
    expect(
      notificationCommand(
        {
          channel: "os",
          category: "question_waiting",
          title: "Penguin has a question",
          body: "A question is waiting in the terminal.",
        },
        "darwin",
        {
          terminalBundleID: "com.mitchellh.ghostty",
        },
      ),
    ).toEqual([
      "/usr/bin/osascript",
      "-e",
      'tell application id "com.mitchellh.ghostty" to display notification "A question is waiting in the terminal." with title "Penguin has a question"',
    ])

    expect(
      notificationCommand(
        {
          channel: "os",
          category: "run_complete",
          title: "Penguin run complete",
          body: "A run finished.",
        },
        "darwin",
        {
          terminalBundleID: "com.mitchellh.ghostty",
          terminalNotifier: "/usr/local/bin/terminal-notifier",
        },
      ),
    ).toEqual([
      "/usr/local/bin/terminal-notifier",
      "-title",
      "Penguin run complete",
      "-message",
      "A run finished.",
      "-sender",
      "com.mitchellh.ghostty",
    ])
  })

  test("builds Linux desktop notification commands", () => {
    expect(
      notificationCommand(
        {
          channel: "os",
          category: "run_failed",
          title: "Penguin run failed",
          body: "Check the terminal",
        },
        "linux",
      ),
    ).toEqual([
      "notify-send",
      "--app-name=Penguin",
      "--expire-time=8000",
      "--urgency",
      "critical",
      "Penguin run failed",
      "Check the terminal",
    ])
  })

  test("builds Windows desktop notification commands without shell interpolation", () => {
    const command = notificationCommand(
      {
        channel: "os",
        category: "question_waiting",
        title: "Penguin's question",
        body: "Continue?",
      },
      "win32",
    )

    expect(command?.slice(0, 6)).toEqual([
      "powershell.exe",
      "-NoProfile",
      "-NonInteractive",
      "-ExecutionPolicy",
      "Bypass",
      "-Command",
    ])
    expect(command?.[6]).toContain("$n.BalloonTipTitle='Penguin''s question';")
    expect(command?.[6]).toContain("$n.BalloonTipText='Continue?';")
  })

  test("delivers sound payloads through an injectable spawn adapter", () => {
    const spawns: string[][] = []
    const logs: string[] = []

    deliverNotificationPayloads(
      [
        {
          channel: "sound",
          category: "question_waiting",
          title: "Penguin has a question",
          body: "Continue?",
          sound: "noot-noot-attention",
        },
      ],
      {
        platform: "darwin",
        assets: {},
        spawn: (command) => spawns.push(command),
        log: (payload) => logs.push(payload.title),
      },
    )

    expect(spawns).toEqual([["/usr/bin/say", "NOOT NOOT"]])
    expect(logs).toEqual(["Penguin has a question"])
  })

  test("terminal mode writes terminal escapes without spawning desktop commands", () => {
    const writes: string[] = []
    const spawns: string[][] = []
    const logs: string[] = []

    deliverNotificationPayloads(
      [
        {
          channel: "terminal",
          category: "question_waiting",
          title: "Penguin has a question",
          body: "Continue?",
        },
      ],
      {
        platform: "darwin",
        write: (text) => writes.push(text),
        spawn: (command) => spawns.push(command),
        log: (payload) => logs.push(payload.title),
      },
    )

    expect(writes).toEqual(["\u001b]9;Penguin has a question;Continue?\u0007"])
    expect(spawns).toEqual([])
    expect(logs).toEqual(["Penguin has a question"])
  })

  test("uses supplied notification assets for icons and sound files", () => {
    expect(
      notificationCommand(
        {
          channel: "sound",
          category: "run_complete",
          title: "Penguin run complete",
          body: "Finished",
          sound: "noot-noot",
        },
        "darwin",
        {
          sounds: {
            "noot-noot": "/tmp/noot.mp3",
          },
        },
      ),
    ).toEqual(["/usr/bin/afplay", "/tmp/noot.mp3"])

    expect(
      notificationCommand(
        {
          channel: "os",
          category: "run_complete",
          title: "Penguin run complete",
          body: "Finished",
        },
        "linux",
        {
          icon: "/tmp/penguin.ico",
        },
      ),
    ).toEqual([
      "notify-send",
      "--app-name=Penguin",
      "--expire-time=8000",
      "--urgency",
      "normal",
      "--icon",
      "/tmp/penguin.ico",
      "Penguin run complete",
      "Finished",
    ])
  })

  test("notifies only mapped attention events", () => {
    const writes: string[] = []

    expect(
      notifyForSyncEvent(
        {
          type: "message.updated",
          properties: {
            sessionID: "ses_1",
          },
        },
        { mode: "bell" },
        { write: (text) => writes.push(text) },
      ),
    ).toEqual([])

    expect(
      notifyForSyncEvent(
        {
          type: "permission.asked",
          properties: {
            id: "perm_1",
            sessionID: "ses_1",
            reason: "Need shell",
          },
        },
        { mode: "bell" },
        { write: (text) => writes.push(text) },
      ),
    ).toHaveLength(1)
    expect(writes).toEqual(["\u0007"])
  })

  test("delivers completion notifications from idle session status events", () => {
    const spawns: string[][] = []
    const delivered = notifyForSyncEvent(
      {
        type: "session.status",
        properties: {
          messageID: "msg_1",
          sessionID: "ses_1",
          status: {
            type: "idle",
          },
        },
      },
      {
        mode: "combined",
        soundPack: "penguin",
      },
      {
        platform: "darwin",
        assets: {
          sounds: {
            "noot-noot": "/tmp/noot.mp3",
          },
        },
        spawn: (command) => spawns.push(command),
      },
    )

    expect(delivered.map((payload) => payload.channel)).toEqual(["os", "sound"])
    expect(spawns).toEqual([
      ["/usr/bin/osascript", "-e", 'display notification "A run finished." with title "Penguin run complete"'],
      ["/usr/bin/afplay", "/tmp/noot.mp3"],
    ])
  })
})
