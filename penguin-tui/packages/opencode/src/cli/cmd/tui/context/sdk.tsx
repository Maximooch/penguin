import { createOpencodeClient, type Event } from "@opencode-ai/sdk/v2"
import { createSimpleContext } from "./helper"
import { createGlobalEmitter } from "@solid-primitives/event-bus"
import { batch, onCleanup, onMount } from "solid-js"

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
    const sdk = createOpencodeClient({
      baseUrl: props.url,
      signal: abort.signal,
      directory: props.directory,
      fetch: props.fetch,
    })
    const penguin = !!props.penguin
    const sessionID = props.sessionID

    const emitter = createGlobalEmitter<{
      [key in Event["type"]]: Extract<Event, { type: key }>
    }>()

    let queue: Event[] = []
    let timer: Timer | undefined
    let last = 0

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

    const clean = (value: string) => value.replace(/<\/?finish_response\b[^>]*>?/g, "")

    const handleEvent = (event: Event) => {
      if (penguin && event.type === "message.part.updated") {
        const part = event.properties.part
        if (part && part.type === "reasoning") return
        if (part && part.type === "text" && typeof part.text === "string") {
          const text = clean(part.text)
          if (text !== part.text) part.text = text
        }
        if (typeof event.properties.delta === "string") {
          const delta = clean(event.properties.delta)
          if (delta !== event.properties.delta) event.properties.delta = delta
        }
      }
      queue.push(event)
      const elapsed = Date.now() - last

      if (timer) return
      // If we just flushed recently (within 16ms), batch this with future events
      // Otherwise, process immediately to avoid latency
      if (elapsed < 16) {
        timer = setTimeout(flush, 16)
        return
      }
      flush()
    }

    const parseJson = (input: string) => {
      try {
        return JSON.parse(input) as Event
      } catch {
        return undefined
      }
    }

    const parseEvent = (input: string) => {
      const data = input
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .join("\n")
      if (!data) return undefined
      return parseJson(data)
    }

    const streamPenguin = async () => {
      const base = new URL("/api/v1/events/sse", props.url)
      if (sessionID) base.searchParams.set("session_id", sessionID)
      if (props.directory) base.searchParams.set("directory", props.directory)
      const reader = await (props.fetch ?? fetch)(base, {
        signal: abort.signal,
        headers: {
          Accept: "text/event-stream",
        },
      })
        .then((res) => res.body)
        .then((body) => body?.getReader())

      if (!reader) return

      const decoder = new TextDecoder()
      const state = { buffer: "" }

      while (true) {
        const chunk = await reader.read()
        if (chunk.done) break
        state.buffer += decoder.decode(chunk.value, { stream: true })
        const parts = state.buffer.split("\n\n")
        state.buffer = parts.pop() ?? ""
        for (const part of parts) {
          const event = parseEvent(part)
          if (!event) continue
          handleEvent(event)
        }
      }
    }

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
          if (abort.signal.aborted) break
          await streamPenguin().catch(() => {})
          if (timer) clearTimeout(timer)
          if (queue.length > 0) {
            flush()
          }
          if (abort.signal.aborted) break
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
      if (timer) clearTimeout(timer)
    })

    return { client: sdk, event: emitter, url: props.url, penguin, sessionID }
  },
})
