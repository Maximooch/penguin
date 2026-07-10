import { describe, expect, test } from "bun:test"
import {
  derivePenguinRunState,
  isPenguinAssistantOpen,
  isPenguinPartActive,
} from "../../src/cli/cmd/tui/component/prompt/penguin-run-state"

describe("Penguin run state", () => {
  test("is idle without pending work, busy status, or open assistant messages", () => {
    expect(
      derivePenguinRunState({
        now: 20_000,
        sessionStatus: { type: "idle" },
      }),
    ).toEqual({
      elapsedMs: 0,
      type: "idle",
    })
  })

  test("keeps the run active while prompt submission is still pending", () => {
    expect(
      derivePenguinRunState({
        localStartedAt: 10_000,
        now: 12_500,
        pending: true,
        sessionStatus: { type: "idle" },
        stream: { status: "connected", lastEventAt: 12_000 },
      }),
    ).toMatchObject({
      elapsedMs: 2_500,
      type: "pending",
    })
  })

  test("keeps the run active while backend session status is busy", () => {
    expect(
      derivePenguinRunState({
        localStartedAt: 10_000,
        now: 13_000,
        sessionStatus: { type: "busy" },
        stream: { status: "connected", lastEventAt: 12_500 },
      }),
    ).toMatchObject({
      elapsedMs: 3_000,
      type: "running",
    })
  })

  test("keeps the run active if an assistant message is still open after idle status", () => {
    expect(
      derivePenguinRunState({
        assistant: {
          role: "assistant",
          time: { created: 10_500 },
        },
        now: 14_000,
        sessionStatus: { type: "idle" },
        stream: { status: "connected", lastEventAt: 13_500 },
        user: {
          role: "user",
          time: { created: 10_000 },
        },
      }),
    ).toMatchObject({
      elapsedMs: 4_000,
      type: "running",
    })
  })

  test("marks active runs as reconnecting while the Penguin stream reconnects", () => {
    expect(
      derivePenguinRunState({
        localStartedAt: 10_000,
        now: 14_000,
        sessionStatus: { type: "busy" },
        stream: { status: "reconnecting", lastEventAt: 13_000 },
      }),
    ).toMatchObject({
      elapsedMs: 4_000,
      lastEventAgeMs: 1_000,
      type: "reconnecting",
    })
  })

  test("marks active runs as stale when no events arrive past the threshold", () => {
    expect(
      derivePenguinRunState({
        localStartedAt: 10_000,
        now: 30_000,
        sessionStatus: { type: "busy" },
        staleAfterMs: 15_000,
        stream: { status: "connected", lastEventAt: 12_000 },
      }),
    ).toMatchObject({
      elapsedMs: 20_000,
      lastEventAgeMs: 18_000,
      type: "stale",
    })
  })

  test("marks a run stale when heartbeats arrive without real progress", () => {
    expect(
      derivePenguinRunState({
        localStartedAt: 10_000,
        now: 30_000,
        sessionStatus: { type: "busy" },
        staleAfterMs: 15_000,
        stream: {
          lastEventAt: 29_500,
          lastProgressAt: 12_000,
          status: "connected",
          tracksProgress: true,
        },
      }),
    ).toMatchObject({
      elapsedMs: 20_000,
      lastEventAgeMs: 500,
      lastProgressAgeMs: 18_000,
      type: "stale",
    })
  })

  test("does not carry an old run's progress age into a new run", () => {
    expect(
      derivePenguinRunState({
        localStartedAt: 30_000,
        now: 31_000,
        pending: true,
        sessionStatus: { type: "busy" },
        staleAfterMs: 15_000,
        stream: {
          lastEventAt: 30_500,
          lastProgressAt: 12_000,
          status: "connected",
          tracksProgress: true,
        },
      }),
    ).toMatchObject({
      elapsedMs: 1_000,
      lastEventAgeMs: 500,
      type: "running",
    })
  })

  test("does not mark a completed final response stale after the session is idle", () => {
    expect(
      derivePenguinRunState({
        assistant: {
          finish: "stop",
          role: "assistant",
          time: { completed: 20_000, created: 10_500 },
        },
        now: 60_000,
        sessionStatus: { type: "idle" },
        staleAfterMs: 15_000,
        stream: { status: "connected", lastEventAt: 25_000 },
        user: {
          role: "user",
          time: { created: 10_000 },
        },
      }),
    ).toEqual({
      elapsedMs: 0,
      type: "idle",
    })
  })

  test("recognizes active tool and reasoning parts", () => {
    expect(isPenguinPartActive({ type: "tool", state: { status: "running" } })).toBe(true)
    expect(isPenguinPartActive({ type: "reasoning", time: { start: 10_000 } })).toBe(true)
    expect(isPenguinPartActive({ type: "tool", state: { status: "completed" } })).toBe(false)
  })

  test("closed assistant messages are not active", () => {
    expect(
      isPenguinAssistantOpen({
        message: {
          finish: "stop",
          role: "assistant",
          time: { created: 10_000 },
        },
      }),
    ).toBe(false)
    expect(
      isPenguinAssistantOpen({
        message: {
          role: "assistant",
          time: { completed: 15_000, created: 10_000 },
        },
      }),
    ).toBe(false)
  })

  test("keeps a completed assistant message active while a tool part is running", () => {
    expect(
      isPenguinAssistantOpen({
        message: {
          role: "assistant",
          time: { completed: 15_000, created: 10_000 },
        },
        parts: [{ type: "tool", state: { status: "running" } }],
      }),
    ).toBe(true)

    expect(
      isPenguinAssistantOpen({
        message: {
          finish: "tool_calls",
          role: "assistant",
          time: { created: 10_000 },
        },
      }),
    ).toBe(true)
  })
})
