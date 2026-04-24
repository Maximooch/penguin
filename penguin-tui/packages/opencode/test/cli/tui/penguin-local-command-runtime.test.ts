import { describe, expect, test } from "bun:test"

import { executePenguinHttpLocalCommand } from "../../../src/cli/cmd/tui/component/prompt/penguin-local-command-runtime"
import type { PenguinLocalCommand } from "../../../src/cli/cmd/tui/component/prompt/penguin-local-command"

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

async function run(command: PenguinLocalCommand, payload: unknown = {}) {
  const records: RequestRecord[] = []
  const result = await executePenguinHttpLocalCommand({
    command: command as any,
    fetch: makeFetch(records, payload),
    baseUrl: "http://127.0.0.1:9010",
    directory: "/tmp/workspace",
  })
  return { records, result }
}

describe("penguin HTTP local command runtime", () => {
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
      { kind: "project_init", projectName: "Demo", blueprintPath: "./blueprint.md" },
      { project: { name: "Demo" }, blueprint: { tasks_created: 2, tasks_updated: 1 } },
    )
    expect(response.records[0]).toEqual({
      url: "http://127.0.0.1:9010/api/v1/projects/init",
      method: "POST",
      body: {
        name: "Demo",
        blueprint_path: "./blueprint.md",
        workspace_path: "/tmp/workspace",
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
      body: { project_identifier: "Demo", continuous: true },
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
      body: { answer: "Use Postgres", answered_by: "tui" },
    })
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
