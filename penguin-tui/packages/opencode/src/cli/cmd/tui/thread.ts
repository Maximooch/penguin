import { cmd } from "@/cli/cmd/cmd"
import { tui } from "./app"
import { Rpc } from "@/util/rpc"
import { type rpc } from "./worker"
import path from "path"
import { UI } from "@/cli/ui"
import { iife } from "@/util/iife"
import { Log } from "@/util/log"
import { withNetworkOptions } from "@/cli/network"
import type { Event } from "@opencode-ai/sdk/v2"
import type { EventSource } from "./context/sdk"
import { profileStartup } from "./util/startup-profile"

declare global {
  const OPENCODE_WORKER_PATH: string
}

type RpcClient = ReturnType<typeof Rpc.client<typeof rpc>>

function createWorkerFetch(client: RpcClient): typeof fetch {
  const fn = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const request = new Request(input, init)
    const body = request.body ? await request.text() : undefined
    const result = await client.call("fetch", {
      url: request.url,
      method: request.method,
      headers: Object.fromEntries(request.headers.entries()),
      body,
    })
    return new Response(result.body, {
      status: result.status,
      headers: result.headers,
    })
  }
  return fn as typeof fetch
}

function createEventSource(client: RpcClient): EventSource {
  return {
    on: (handler) => client.on<Event>("event", handler),
  }
}

export const TuiThreadCommand = cmd({
  command: "$0 [project]",
  describe: "start Penguin TUI",
  builder: (yargs) =>
    withNetworkOptions(yargs)
      .positional("project", {
        type: "string",
        describe: "path to start Penguin in",
      })
      .option("model", {
        type: "string",
        alias: ["m"],
        describe: "model to use in the format of provider/model",
      })
      .option("continue", {
        alias: ["c"],
        describe: "continue the last session",
        type: "boolean",
      })
      .option("session", {
        alias: ["s"],
        type: "string",
        describe: "session id to continue",
      })
      .option("prompt", {
        type: "string",
        describe: "prompt to use",
      })
      .option("agent", {
        type: "string",
        describe: "agent to use",
      })
      .option("url", {
        type: "string",
        describe: "penguin web server url",
      }),
  handler: async (args) => {
    profileStartup("thread.handler.start", {
      has_project: Boolean(args.project),
      has_prompt: Boolean(args.prompt),
      has_session: Boolean(args.session),
    })
    // Resolve relative paths against PWD to preserve behavior when using --cwd flag
    const cwdStart = Date.now()
    const baseCwd = process.env.PWD ?? process.cwd()
    const cwd = args.project ? path.resolve(baseCwd, args.project) : baseCwd
    profileStartup("thread.cwd.done", {
      duration_ms: Date.now() - cwdStart,
      cwd,
    })
    const localWorker = new URL("./worker.ts", import.meta.url)
    const distWorker = new URL("./cli/cmd/tui/worker.js", import.meta.url)
    const workerPathStart = Date.now()
    const workerPath = await iife(async () => {
      if (typeof OPENCODE_WORKER_PATH !== "undefined") return OPENCODE_WORKER_PATH
      if (await Bun.file(distWorker).exists()) return distWorker
      return localWorker
    })
    profileStartup("thread.worker_path.done", {
      duration_ms: Date.now() - workerPathStart,
      worker_path: String(workerPath),
    })
    try {
      const chdirStart = Date.now()
      process.chdir(cwd)
      profileStartup("thread.chdir.done", {
        duration_ms: Date.now() - chdirStart,
      })
    } catch (e) {
      UI.error("Failed to change directory to " + cwd)
      return
    }

    let client: RpcClient | undefined
    function ensureClient() {
      if (client) return client
      const workerStart = Date.now()
      const worker = new Worker(workerPath, {
        env: Object.fromEntries(
          Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined),
        ),
      })
      worker.onerror = (e) => {
        Log.Default.error(e)
      }
      client = Rpc.client<typeof rpc>(worker)
      profileStartup("thread.worker.spawn.done", {
        duration_ms: Date.now() - workerStart,
      })
      return client
    }
    process.on("uncaughtException", (e) => {
      Log.Default.error(e)
    })
    process.on("unhandledRejection", (e) => {
      Log.Default.error(e)
    })
    process.on("SIGUSR2", async () => {
      await ensureClient().call("reload", undefined)
    })

    const promptStart = Date.now()
    const prompt = await iife(async () => {
      const piped = !process.stdin.isTTY ? await Bun.stdin.text() : undefined
      if (!args.prompt) return piped
      return piped ? piped + "\n" + args.prompt : args.prompt
    })
    profileStartup("thread.prompt.done", {
      duration_ms: Date.now() - promptStart,
      stdin_tty: process.stdin.isTTY,
      has_prompt: Boolean(prompt),
    })

    const base = args.url ?? process.env.PENGUIN_WEB_URL ?? "http://127.0.0.1:9000"
    const sessionID = args.session
    const url = base
    const customFetch = undefined
    const events = undefined

    profileStartup("thread.tui.call", {
      url,
      has_session: Boolean(sessionID),
    })
    const tuiPromise = tui({
      url,
      directory: cwd,
      fetch: customFetch,
      events,
      penguin: true,
      sessionID,
      args: {
        continue: args.continue,
        sessionID: args.session,
        agent: args.agent,
        model: args.model,
        prompt,
      },
      onExit: async () => {
        await client?.call("shutdown", undefined)
      },
    })

    setTimeout(() => {
      ensureClient().call("checkUpgrade", { directory: cwd }).catch(() => {})
    }, 1000)

    await tuiPromise
  },
})
