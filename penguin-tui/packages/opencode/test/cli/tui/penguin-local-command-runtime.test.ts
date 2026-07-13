import { describe, expect, test } from "bun:test"

import {
  emitPenguinOptimisticGoal,
  executePenguinHttpLocalCommand,
  shouldEmitPenguinOptimisticGoal,
} from "../../../src/cli/cmd/tui/component/prompt/penguin-local-command-runtime"
import {
  parsePenguinLocalCommand,
  type PenguinLocalCommand,
} from "../../../src/cli/cmd/tui/component/prompt/penguin-local-command"

type RequestRecord = {
  url: string
  method: string
  body?: any
}

function makeFetch(records: RequestRecord[], payload: unknown = {}): typeof fetch {
  return (async (input: URL | RequestInfo, init?: RequestInit) => {
    const url = input instanceof URL ? input.toString() : String(input)
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined
    records.push({ url, method: init?.method ?? "GET", body })
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })
  }) as typeof fetch
}

async function run(command: PenguinLocalCommand, payload: unknown = {}, sessionID?: string) {
  const records: RequestRecord[] = []
  const result = await executePenguinHttpLocalCommand({
    command: command as any,
    fetch: makeFetch(records, payload),
    baseUrl: "http://127.0.0.1:9010",
    directory: "/tmp/workspace",
    sessionID,
  })
  return { records, result }
}

describe("penguin HTTP local command runtime", () => {
  test("does not create an optimistic row for an empty goal objective", () => {
    const command = parsePenguinLocalCommand("/goal --replace")
    if (!command) throw new Error("expected command")

    expect(shouldEmitPenguinOptimisticGoal(command)).toBe(false)
  })

  test("emits the exact goal command with the stable client message id", () => {
    const command = parsePenguinLocalCommand('/goal "Ship it"   --replace')
    if (!command || command.kind !== "goal_set") throw new Error("expected goal_set command")
    const events: Array<{ type: string; event: unknown }> = []

    const client = emitPenguinOptimisticGoal({
      command,
      agentName: "general",
      emit: (event) => events.push({ type: event.type, event }),
      messageID: "msg_goal_1",
      model: { providerID: "openai", modelID: "gpt-5" },
      now: 123,
      partID: "part_goal_1",
      sessionID: "ses_goal",
    })

    expect(client).toBe("msg_goal_1")
    expect(events).toEqual([
      {
        type: "message.updated",
        event: {
          type: "message.updated",
          properties: {
            info: {
              id: "msg_goal_1",
              sessionID: "ses_goal",
              role: "user",
              time: { created: 123 },
              agent: "general",
              model: { providerID: "openai", modelID: "gpt-5" },
            },
          },
        },
      },
      {
        type: "message.part.updated",
        event: {
          type: "message.part.updated",
          properties: {
            part: {
              id: "part_goal_1",
              sessionID: "ses_goal",
              messageID: "msg_goal_1",
              type: "text",
              text: '/goal "Ship it"   --replace',
              time: { start: 123, end: 123 },
            },
            delta: '/goal "Ship it"   --replace',
          },
        },
      },
      {
        type: "session.status",
        event: {
          type: "session.status",
          properties: {
            sessionID: "ses_goal",
            status: { type: "busy" },
          },
        },
      },
    ])
  })

  test("routes project commands to project endpoints", async () => {
    let response = await run(
      { kind: "project_create", projectName: "Demo", description: "Desc" },
      { name: "Demo" },
    )
    expect(response.records).toEqual([
      {
        url: "http://127.0.0.1:9010/api/v1/projects",
        method: "POST",
        body: {
          name: "Demo",
          description: "Desc",
          workspace_path: "/tmp/workspace",
        },
      },
    ])
    expect(response.result.message).toBe("Project created: Demo")

    response = await run(
      { kind: "project_init", projectName: "Demo", blueprintPath: "./blueprint.md", workspacePath: "/tmp/demo-workspace" },
      { project: { name: "Demo" }, blueprint: { tasks_created: 2, tasks_updated: 1 } },
    )
    expect(response.records[0]).toEqual({
      url: "http://127.0.0.1:9010/api/v1/projects/init",
      method: "POST",
      body: {
        name: "Demo",
        blueprint_path: "./blueprint.md",
        workspace_path: "/tmp/demo-workspace",
      },
    })
    expect(response.result.message).toBe("Project initialized: Demo (2 created, 1 updated)")

    response = await run({ kind: "project_list" }, { projects: [{ id: "p1" }] })
    expect(response.records[0]).toEqual({
      url: "http://127.0.0.1:9010/api/v1/projects",
      method: "GET",
      body: undefined,
    })
    expect(response.result.message).toBe("Projects: 1")

    response = await run({ kind: "project_show", projectIdentifier: "project-1" }, { name: "Demo", tasks: [] })
    expect(response.records[0].url).toBe("http://127.0.0.1:9010/api/v1/projects/project-1")
    expect(response.records[0].method).toBe("GET")

    response = await run({ kind: "project_start", projectIdentifier: "Demo" }, { project: { name: "Demo" } })
    expect(response.records[0]).toEqual({
      url: "http://127.0.0.1:9010/api/v1/projects/start",
      method: "POST",
      body: { project_identifier: "Demo", continuous: true, directory: "/tmp/workspace" },
    })

    response = await run({ kind: "project_delete", projectIdentifier: "project-1" }, { message: "deleted" })
    expect(response.records[0].url).toBe("http://127.0.0.1:9010/api/v1/projects/project-1")
    expect(response.records[0].method).toBe("DELETE")
  })

  test("routes task commands to task endpoints", async () => {
    let response = await run(
      { kind: "task_create", projectId: "project-1", title: "Write tests", priority: 3 },
      { title: "Write tests" },
    )
    expect(response.records[0]).toEqual({
      url: "http://127.0.0.1:9010/api/v1/tasks",
      method: "POST",
      body: {
        project_id: "project-1",
        title: "Write tests",
        priority: 3,
      },
    })

    response = await run({ kind: "task_list", projectId: "project-1", status: "active" }, { tasks: [] })
    expect(response.records[0].url).toBe("http://127.0.0.1:9010/api/v1/tasks?project_id=project-1&status=active")
    expect(response.records[0].method).toBe("GET")

    response = await run({ kind: "task_show", taskId: "task-1" }, { title: "Task", status: "active" })
    expect(response.records[0].url).toBe("http://127.0.0.1:9010/api/v1/tasks/task-1")
    expect(response.records[0].method).toBe("GET")

    response = await run({ kind: "task_start", taskId: "task-1" }, { message: "started" })
    expect(response.records[0].url).toBe("http://127.0.0.1:9010/api/v1/tasks/task-1/start")
    expect(response.records[0].method).toBe("POST")

    response = await run({ kind: "task_complete", taskId: "task-1" }, { message: "completed" })
    expect(response.records[0].url).toBe("http://127.0.0.1:9010/api/v1/tasks/task-1/complete")
    expect(response.records[0].method).toBe("POST")

    response = await run({ kind: "task_execute", taskId: "task-1" }, { task: { title: "Task" } })
    expect(response.records[0].url).toBe("http://127.0.0.1:9010/api/v1/tasks/task-1/execute")
    expect(response.records[0].method).toBe("POST")

    response = await run({ kind: "task_delete", taskId: "task-1" }, { message: "deleted" })
    expect(response.records[0].url).toBe("http://127.0.0.1:9010/api/v1/tasks/task-1")
    expect(response.records[0].method).toBe("DELETE")

    response = await run(
      { kind: "task_clarification_resume", taskId: "task-1", answer: "Use Postgres" },
      { task: { title: "Task" } },
    )
    expect(response.records[0]).toEqual({
      url: "http://127.0.0.1:9010/api/v1/tasks/task-1/clarification/resume",
      method: "POST",
      body: { answer: "Use Postgres", answered_by: "tui", directory: "/tmp/workspace" },
    })
  })

  test("sets and runs a goal", async () => {
    const records: RequestRecord[] = []
    let call = 0
    const result = await executePenguinHttpLocalCommand({
      command: {
        kind: "goal_set",
        objective: "Ship it",
        replace: false,
        displayCommand: '/goal "Ship it"',
      },
      fetch: (async (input: URL | RequestInfo, init?: RequestInit) => {
        const url = input instanceof URL ? input.toString() : String(input)
        const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined
        records.push({ url, method: init?.method ?? "GET", body })
        call++
        return new Response(
          JSON.stringify(
            call === 1
              ? { goal: { objective: "Ship it", status: "active" } }
              : { goal: { objective: "Ship it", status: "complete" } },
          ),
          { status: 200, headers: { "Content-Type": "application/json" } },
        )
      }) as typeof fetch,
      baseUrl: "http://127.0.0.1:9010",
      directory: "/tmp/workspace",
      sessionID: "ses_goal",
      clientMessageID: "msg_goal_1",
      clientPartID: "part_goal_1",
    })

    expect(records).toEqual([
      {
        url: "http://127.0.0.1:9010/api/v1/session/ses_goal/goal",
        method: "POST",
        body: {
          objective: "Ship it",
          replace: false,
          display_command: '/goal "Ship it"',
          client_message_id: "msg_goal_1",
          client_part_id: "part_goal_1",
        },
      },
      {
        url: "http://127.0.0.1:9010/api/v1/session/ses_goal/goal/run",
        method: "POST",
        body: { directory: "/tmp/workspace" },
      },
    ])
    expect(result.message).toBe("Goal complete: Ship it")
  })

  test("routes a pasted multiline goal to goal endpoints, never chat", async () => {
    const pasted = "/goal \nShip the durable goal route\n--replace"
    const command = parsePenguinLocalCommand(pasted)
    if (!command || command.kind !== "goal_set") throw new Error("expected goal_set command")

    const response = await run(
      command,
      { goal: { objective: "Ship the durable goal route", status: "active" } },
      "ses_goal_paste",
    )

    expect(response.records.map((record) => record.url)).toEqual([
      "http://127.0.0.1:9010/api/v1/session/ses_goal_paste/goal",
      "http://127.0.0.1:9010/api/v1/session/ses_goal_paste/goal/run",
    ])
    expect(response.records[0].body).toEqual({
      objective: "Ship the durable goal route",
      replace: true,
    })
    expect(response.records.some((record) => record.url.includes("/chat/message"))).toBe(false)
  })

  test("keeps a saved goal visible when its run request fails", async () => {
    let call = 0
    const result = await executePenguinHttpLocalCommand({
      command: {
        kind: "goal_set",
        objective: "Ship it",
        replace: false,
        displayCommand: "/goal Ship it",
      },
      fetch: (async () => {
        call++
        if (call === 1) {
          return new Response(JSON.stringify({ goal: { status: "active" } }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        }
        return new Response("session is busy", { status: 409 })
      }) as unknown as typeof fetch,
      baseUrl: "http://127.0.0.1:9010",
      directory: "/tmp/workspace",
      sessionID: "ses_goal",
      clientMessageID: "msg_goal_1",
      clientPartID: "part_goal_1",
    })

    expect(result).toEqual({
      variant: "warning",
      message:
        "Goal saved, but its run did not start: session is busy",
    })
    expect(call).toBe(2)
  })

  test("omits display-message correlation fields when no client message id exists", async () => {
    const response = await run(
      {
        kind: "goal_set",
        objective: "Ship it",
        replace: false,
        displayCommand: '/goal "Ship it"',
      },
      { goal: { objective: "Ship it", status: "complete" } },
      "ses_goal",
    )

    expect(response.records[0].body).toEqual({
      objective: "Ship it",
      replace: false,
    })
  })

  test("confirms and retries an unfinished-goal replacement before running", async () => {
    const records: RequestRecord[] = []
    let call = 0
    const confirmations: string[] = []
    const result = await executePenguinHttpLocalCommand({
      command: {
        kind: "goal_set",
        objective: "Replace safely",
        replace: false,
        displayCommand: "/goal Replace safely",
      },
      fetch: (async (input: URL | RequestInfo, init?: RequestInit) => {
        const url = input instanceof URL ? input.toString() : String(input)
        const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined
        records.push({ url, method: init?.method ?? "GET", body })
        call++
        if (call === 1) {
          return new Response(JSON.stringify({ detail: { code: "goal_replace_required" } }), {
            status: 409,
          })
        }
        return new Response(JSON.stringify({ goal: { objective: "Replace safely", status: "complete" } }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }) as typeof fetch,
      baseUrl: "http://127.0.0.1:9010",
      clientMessageID: "msg_goal_replace",
      clientPartID: "part_goal_replace",
      confirmGoalReplace: async (objective) => {
        confirmations.push(objective)
        return true
      },
      directory: "/tmp/workspace",
      sessionID: "ses_goal",
    })

    expect(confirmations).toEqual(["Replace safely"])
    expect(records).toHaveLength(3)
    expect(records[1].body).toMatchObject({
      replace: true,
      display_command: "/goal Replace safely --replace",
      client_message_id: "msg_goal_replace",
      client_part_id: "part_goal_replace",
    })
    expect(records[2].url).toEndWith("/api/v1/session/ses_goal/goal/run")
    expect(result.message).toBe("Goal complete: Replace safely")
  })

  test("does not run when unfinished-goal replacement is cancelled", async () => {
    const records: RequestRecord[] = []
    const result = await executePenguinHttpLocalCommand({
      command: {
        kind: "goal_set",
        objective: "Do not replace",
        replace: false,
        displayCommand: "/goal Do not replace",
      },
      fetch: (async (input: URL | RequestInfo, init?: RequestInit) => {
        const url = input instanceof URL ? input.toString() : String(input)
        const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined
        records.push({ url, method: init?.method ?? "GET", body })
        return new Response(JSON.stringify({ detail: { code: "goal_replace_required" } }), {
          status: 409,
        })
      }) as typeof fetch,
      baseUrl: "http://127.0.0.1:9010",
      clientMessageID: "msg_goal_cancel_replace",
      clientPartID: "part_goal_cancel_replace",
      confirmGoalReplace: async () => false,
      directory: "/tmp/workspace",
      sessionID: "ses_goal",
    })

    expect(records).toHaveLength(1)
    expect(result).toEqual({
      variant: "warning",
      message: "Goal replacement cancelled",
      cancelled: true,
    })
  })

  test("routes goal status, pause, resume, run, and clear", async () => {
    let response = await run(
      { kind: "goal_status" },
      {
        goal: {
          id: "goal_1",
          objective: "Ship it",
          status: "active",
          revision: 1,
          token_budget: 50_000,
          tokens_used: 1_250,
          time_used_seconds: 4,
          created_at: "2026-07-09T12:00:00+00:00",
          updated_at: "2026-07-09T12:00:00+00:00",
          active_run_id: null,
          active_run_owner: null,
          active_run_started_at: null,
          last_run_id: null,
          last_result: null,
          metadata: {},
        },
      },
      "ses_goal",
    )
    expect(response.records[0].method).toBe("GET")
    expect(response.result.message).toBe("Goal: active — Ship it (1,250 / 50,000 tokens)")

    response = await run({ kind: "goal_pause" }, { goal: { objective: "Ship it", status: "paused" } }, "ses_goal")
    expect(response.records[0].body).toEqual({ status: "paused" })

    response = await run({ kind: "goal_resume" }, { goal: { objective: "Ship it", status: "active" } }, "ses_goal")
    expect(response.records).toHaveLength(2)
    expect(response.records[0].body).toEqual({ status: "active" })
    expect(response.records[1].url).toEndWith("/api/v1/session/ses_goal/goal/run")

    response = await run({ kind: "goal_run" }, { goal: { objective: "Ship it", status: "active" } }, "ses_goal")
    expect(response.records[0].url).toEndWith("/api/v1/session/ses_goal/goal/run")

    response = await run({ kind: "goal_clear" }, { goal: null }, "ses_goal")
    expect(response.records[0].method).toBe("DELETE")
  })

  test("returns warnings instead of fetching for missing required arguments", async () => {
    const records: RequestRecord[] = []
    const result = await executePenguinHttpLocalCommand({
      command: { kind: "project_start" },
      fetch: makeFetch(records),
      baseUrl: "http://127.0.0.1:9010",
      directory: "/tmp/workspace",
    })

    expect(records).toEqual([])
    expect(result).toEqual({ variant: "warning", message: "Usage: /project start <project-id-or-name>" })
  })
})
