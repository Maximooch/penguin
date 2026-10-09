// Isolated manual smoke server: bun test/fixture/terminal-compat-server.ts
// Launch with a fresh XDG_STATE_HOME and --url http://127.0.0.1:9010.
// Dismiss the provider picker; select Terminal compatibility test in /sessions.
// POST /test/working, /test/done, /test/error, /test/question to drive states.
const sessionID = "ses_terminal_test"
const session = {
  id: sessionID,
  slug: "terminal-test",
  projectID: "test",
  directory: process.cwd(),
  title: "Terminal compatibility test",
  version: "1",
  time: { created: Date.now(), updated: Date.now() },
}
const streams = new Set<ReadableStreamDefaultController<Uint8Array>>()
function emit(type: string, properties: Record<string, unknown>) {
  const bytes = new TextEncoder().encode(`data: ${JSON.stringify({ type, properties })}\n\n`)
  for (const stream of streams) stream.enqueue(bytes)
}
Bun.serve({
  hostname: "127.0.0.1",
  port: Number(process.env.PORT ?? 9010),
  idleTimeout: 0,
  fetch(request) {
    const path = new URL(request.url).pathname
    if (path === "/api/v1/events/sse") {
      let controller: ReadableStreamDefaultController<Uint8Array>
      return new Response(
        new ReadableStream<Uint8Array>({
          start(value) {
            controller = value
            streams.add(value)
            value.enqueue(new TextEncoder().encode(": connected\n\n"))
          },
          cancel() {
            streams.delete(controller)
          },
        }),
        { headers: { "Content-Type": "text/event-stream" } },
      )
    }
    if (request.method === "POST" && path.startsWith("/test/")) {
      const state = path.split("/").at(-1)
      if (state === "question")
        emit("question.asked", {
          id: "question_test",
          sessionID,
          questions: [
            {
              header: "Smoke test",
              question: "Continue?",
              options: [{ label: "Yes", description: "Continue testing" }],
            },
          ],
        })
      else if (state === "error")
        emit("session.error", { sessionID, error: { name: "UnknownError", data: { message: "Smoke test error" } } })
      else emit("session.status", { sessionID, status: { type: state === "working" ? "busy" : "idle" } })
      return Response.json({ clients: streams.size })
    }
    if (path === "/api/v1/notifications/config") return Response.json({ mode: "terminal" })
    if (path.endsWith("/access")) return Response.json({ session_id: sessionID, mode: "workspace" })
    if (path === "/session") return Response.json([session])
    if (path === `/session/${sessionID}`) return Response.json(session)
    if (path === "/config") return Response.json({})
    if (path === "/provider") return Response.json({ all: [], connected: [], default: {} })
    if (path === "/config/providers") return Response.json({ providers: [], default: {} })
    if (path === "/provider/auth") return Response.json({})
    if (path.endsWith("/abort")) {
      emit("session.status", { sessionID, status: { type: "idle" } })
      return Response.json(true)
    }
    if (path.includes("/question/")) {
      emit("question.replied", { sessionID, requestID: "question_test", answers: [["Yes"]] })
      return Response.json(true)
    }
    return Response.json([])
  },
})
console.log("Terminal smoke server on http://127.0.0.1:9010 (no provider calls)")
