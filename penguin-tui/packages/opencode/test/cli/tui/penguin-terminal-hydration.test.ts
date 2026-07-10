import { describe, expect, test } from "bun:test"
import { createRoot, createSignal } from "solid-js"
import { mountPenguinTerminalHydration } from "../../../src/cli/cmd/tui/component/prompt/penguin-terminal-hydration"
import {
  parsePenguinPromptTerminal,
  type PenguinPromptTerminal,
} from "../../../src/cli/cmd/tui/component/prompt/penguin-send"

function terminalResponse(status: string): Response {
  return new Response(
    JSON.stringify({
      response: "partial",
      partial_response: `partial ${status}`,
      action_results: [],
      action_count: 0,
      status,
      terminal_reason: status,
      state: "stalled",
      completed: false,
      recoverable: true,
      aborted: false,
      cancelled: false,
      error: null,
      continuation: null,
      actions: [],
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  )
}

const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

describe("mounted Penguin terminal hydration", () => {
  test("renders durable incomplete truth after mount", async () => {
    const requests: string[] = []
    const terminals: Array<PenguinPromptTerminal | undefined> = []
    const fetcher = (async (input: RequestInfo | URL) => {
      const url = input instanceof URL ? input : new URL(String(input))
      requests.push(url.pathname)
      return terminalResponse(url.pathname.endsWith("session-two/terminal") ? "max_iterations" : "stalled")
    }) as unknown as typeof fetch

    let dispose!: () => void
    createRoot((cleanup) => {
      dispose = cleanup
      const [sessionID] = createSignal("session-one")
      mountPenguinTerminalHydration({
        active: () => true,
        baseUrl: "http://127.0.0.1:8080",
        directory: () => "/tmp/project",
        fetch: fetcher,
        locallyActive: () => false,
        onTerminal: (terminal) => terminals.push(terminal),
        sessionID,
      })
    })

    await flush()
    expect(terminals.at(-1)?.status).toBe("stalled")
    expect(requests).toEqual(["/api/v1/session/session-one/terminal"])
    dispose()
  })

  test("does not overwrite a locally active submission", async () => {
    const terminals: PenguinPromptTerminal[] = []
    let dispose!: () => void
    createRoot((cleanup) => {
      dispose = cleanup
      mountPenguinTerminalHydration({
        active: () => true,
        baseUrl: "http://127.0.0.1:8080",
        directory: () => undefined,
        fetch: (async () => terminalResponse("stalled")) as unknown as typeof fetch,
        locallyActive: () => true,
        onTerminal: (terminal) => {
          if (terminal) terminals.push(terminal)
        },
        sessionID: () => "session-one",
      })
    })

    await flush()
    expect(terminals).toEqual([])
    dispose()
  })

  test("does not apply a stale hydration response after a local terminal transition", async () => {
    const terminals: PenguinPromptTerminal[] = []
    const pending: Array<(response: Response) => void> = []
    const fetcher = (() =>
      new Promise<Response>((resolve) => {
        pending.push(resolve)
      })) as unknown as typeof fetch

    let dispose!: () => void
    let invalidate!: () => void
    let readEpoch!: () => number
    createRoot((cleanup) => {
      dispose = cleanup
      const [epoch, setEpoch] = createSignal(0)
      readEpoch = epoch
      invalidate = () => setEpoch((value) => value + 1)
      mountPenguinTerminalHydration({
        active: () => true,
        baseUrl: "http://127.0.0.1:8080",
        directory: () => undefined,
        epoch,
        fetch: fetcher,
        locallyActive: () => false,
        onTerminal: (terminal) => {
          if (terminal) terminals.push(terminal)
        },
        sessionID: () => "session-one",
      })
    })

    await flush()
    expect(pending).toHaveLength(1)
    invalidate()
    expect(readEpoch()).toBe(1)
    terminals.push(
      parsePenguinPromptTerminal({
        status: "max_iterations",
        state: "max_iterations",
        completed: false,
        recoverable: true,
      }),
    )
    pending[0](terminalResponse("stalled"))
    await flush()

    expect(terminals.map((terminal) => terminal.status)).toEqual(["max_iterations"])
    dispose()
  })
})
