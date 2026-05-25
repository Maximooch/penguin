import { createOpencodeClient, type Event } from "@opencode-ai/sdk/v2"
import { createSimpleContext } from "./helper"
import { createGlobalEmitter } from "@solid-primitives/event-bus"
import { batch, createEffect, createSignal, onCleanup, onMount } from "solid-js"
import { useRoute } from "./route"
import { getPenguinAuthHeaders } from "./penguin-auth"
import { cleanPenguinEvent, streamPenguinEvents } from "./penguin-event-stream"

export type EventSource = {
  on: (handler: (event: Event) => void) => () => void
}

export const { use: useSDK, provider: SDKProvider } = createSimpleContext({
  name: "SDK",
  init: (props: {
    url: string
    directory?: string
    fetch?: typeof fetch
    events?: EventSource
    penguin?: boolean
    sessionID?: string
  }) => {
    const abort = new AbortController()
    const headers = props.penguin ? getPenguinAuthHeaders() : undefined
    const request = ((input: RequestInfo | URL, init?: RequestInit) => {
      const base = props.fetch ?? fetch
      const next = new Request(input, init)
      if (headers) {
        for (const [key, value] of Object.entries(headers)) {
          next.headers.set(key, value)
        }
      }
      return base(next)
    }) as typeof fetch
    const sdk = createOpencodeClient({
      baseUrl: props.url,
      signal: abort.signal,
      directory: props.directory,
      fetch: request,
      headers,
    })
    const penguin = !!props.penguin
    const route = useRoute()
    const sessionID = () => (route.data.type === "session" ? route.data.sessionID : props.sessionID)

    const emitter = createGlobalEmitter<{
      [key in Event["type"]]: Extract<Event, { type: key }>
    }>()

    let queue: Event[] = []
    let timer: Timer | undefined
    let last = 0
    let streamAbort: AbortController | undefined
    const auth = { denied: false }
    const [stream, setStream] = createSignal<{
      lastEventAt?: number
      status: "idle" | "connecting" | "connected" | "reconnecting" | "denied"
    }>({
      status: penguin ? "connecting" : "idle",
    })

    const flush = () => {
      if (queue.length === 0) return
      const events = queue
      queue = []
      timer = undefined
      last = Date.now()
      // Batch all event emissions so all store updates result in a single render
      batch(() => {
        for (const event of events) {
          emitter.emit(event.type, event)
        }
      })
    }

    const handleEvent = (event: Event) => {
      const now = Date.now()
      if (penguin) {
        setStream({
          lastEventAt: now,
          status: "connected",
        })
      }
      queue.push(penguin ? cleanPenguinEvent(event) : event)
      const elapsed = now - last

      if (timer) return
      // If we just flushed recently (within 16ms), batch this with future events
      // Otherwise, process immediately to avoid latency
      if (elapsed < 16) {
        timer = setTimeout(flush, 16)
        return
      }
      flush()
    }

    const streamPenguin = async () => {
      const activeSessionID = sessionID()
      streamAbort = new AbortController()
      const currentStreamAbort = streamAbort
      setStream((current) => ({
        lastEventAt: current.lastEventAt,
        status: current.lastEventAt ? "reconnecting" : "connecting",
      }))

      await streamPenguinEvents<Event>({
        baseUrl: props.url,
        directory: props.directory,
        fetch: request,
        sessionID: activeSessionID,
        signal: currentStreamAbort.signal,
        isCurrentSession: () => sessionID() === activeSessionID,
        onOpen: () => {
          setStream((current) => ({
            lastEventAt: current.lastEventAt,
            status: "connected",
          }))
        },
        onUnauthorized: () => {
          auth.denied = true
          setStream((current) => ({
            lastEventAt: current.lastEventAt,
            status: "denied",
          }))
          console.error("Penguin SSE unauthorized; restart the TUI to refresh local auth")
        },
        onEvent: handleEvent,
      })
    }

    createEffect(() => {
      if (!penguin) return
      sessionID()
      auth.denied = false
      streamAbort?.abort()
    })

    onMount(async () => {
      // If an event source is provided, use it instead of SSE
      if (props.events) {
        const unsub = props.events.on(handleEvent)
        onCleanup(unsub)
        return
      }

      if (penguin) {
        const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))
        while (true) {
          if (abort.signal.aborted || auth.denied) break
          await streamPenguin().catch(() => {})
          if (timer) clearTimeout(timer)
          if (queue.length > 0) {
            flush()
          }
          if (abort.signal.aborted || auth.denied) break
          setStream((current) => ({
            lastEventAt: current.lastEventAt,
            status: "reconnecting",
          }))
          await wait(250)
        }
        return
      }

      // Fall back to SSE
      while (true) {
        if (abort.signal.aborted) break
        const events = await sdk.event.subscribe(
          {},
          {
            signal: abort.signal,
          },
        )

        for await (const event of events.stream) {
          handleEvent(event)
        }

        // Flush any remaining events
        if (timer) clearTimeout(timer)
        if (queue.length > 0) {
          flush()
        }
      }
    })

    onCleanup(() => {
      abort.abort()
      streamAbort?.abort()
      if (timer) clearTimeout(timer)
    })

    return {
      client: sdk,
      event: emitter,
      fetch: request,
      url: props.url,
      directory: props.directory,
      penguin,
      get stream() {
        return stream()
      },
      get sessionID() {
        return sessionID()
      },
    }
  },
})
