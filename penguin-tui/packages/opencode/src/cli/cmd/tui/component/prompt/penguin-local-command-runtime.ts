import type { PenguinLocalCommand } from "./penguin-local-command"

type PenguinHttpCommand = Extract<
  PenguinLocalCommand,
  | { kind: "project_create" }
  | { kind: "project_init" }
  | { kind: "project_list" }
  | { kind: "project_show" }
  | { kind: "project_delete" }
  | { kind: "project_start" }
  | { kind: "task_create" }
  | { kind: "task_list" }
  | { kind: "task_show" }
  | { kind: "task_start" }
  | { kind: "task_complete" }
  | { kind: "task_execute" }
  | { kind: "task_delete" }
  | { kind: "task_clarification_resume" }
>

export type PenguinLocalCommandFetch = (input: URL, init?: RequestInit) => Promise<Response>

export type PenguinCommandResult = {
  variant: "success" | "warning"
  message: string
}

export function penguinHttpLocalCommandNeedsSession(command: PenguinLocalCommand): boolean {
  return (
    command.kind === "project_start" ||
    command.kind === "task_execute" ||
    command.kind === "task_clarification_resume"
  )
}

export function isPenguinHttpLocalCommand(command: PenguinLocalCommand): command is PenguinHttpCommand {
  return command.kind.startsWith("project_") || command.kind.startsWith("task_")
}

function requireArg(value: string | undefined, usage: string): string | undefined {
  return value || undefined
}

function usage(message: string): PenguinCommandResult {
  return { variant: "warning", message: `Usage: ${message}` }
}

async function fetchJson(
  fetcher: PenguinLocalCommandFetch,
  baseUrl: string | URL,
  path: string,
  init?: RequestInit,
): Promise<unknown> {
  const response = await fetcher(new URL(path, baseUrl), init)
  if (!response.ok) {
    const detail = await response.text().catch(() => `${path} failed`)
    throw new Error(detail)
  }
  return response.json()
}

function objectPayload(value: unknown): Record<string, any> {
  return value && typeof value === "object" ? (value as Record<string, any>) : {}
}

export async function executePenguinHttpLocalCommand(options: {
  command: PenguinHttpCommand
  fetch: PenguinLocalCommandFetch
  baseUrl: string | URL
  directory: string
  sessionID?: string
}): Promise<PenguinCommandResult> {
  const { command, fetch, baseUrl, directory, sessionID } = options

  if (command.kind === "project_create") {
    const projectName = requireArg(command.projectName, "/project create <name> [--description <text>] [--workspace <path>]")
    if (!projectName) return usage("/project create <name> [--description <text>] [--workspace <path>]")
    const payload = objectPayload(
      await fetchJson(fetch, baseUrl, "/api/v1/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: projectName,
          description: command.description,
          workspace_path: command.workspacePath ?? directory,
        }),
      }),
    )
    return { variant: "success", message: `Project created: ${payload.name ?? projectName}` }
  }

  if (command.kind === "project_init") {
    const projectName = requireArg(command.projectName, "/project init <name> [--blueprint <path>] [--workspace <path>]")
    if (!projectName) return usage("/project init <name> [--blueprint <path>] [--workspace <path>]")
    const payload = objectPayload(
      await fetchJson(fetch, baseUrl, "/api/v1/projects/init", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: projectName,
          blueprint_path: command.blueprintPath,
          workspace_path: command.workspacePath ?? directory,
        }),
      }),
    )
    const blueprint = objectPayload(payload.blueprint)
    const taskSummary = payload.blueprint ? ` (${blueprint.tasks_created ?? 0} created, ${blueprint.tasks_updated ?? 0} updated)` : ""
    return { variant: "success", message: `Project initialized: ${objectPayload(payload.project).name ?? projectName}${taskSummary}` }
  }

  if (command.kind === "project_list") {
    const payload = objectPayload(await fetchJson(fetch, baseUrl, "/api/v1/projects"))
    return { variant: "success", message: `Projects: ${Array.isArray(payload.projects) ? payload.projects.length : 0}` }
  }

  if (command.kind === "project_show") {
    const projectIdentifier = requireArg(command.projectIdentifier, "/project show <project-id>")
    if (!projectIdentifier) return usage("/project show <project-id>")
    const payload = objectPayload(await fetchJson(fetch, baseUrl, `/api/v1/projects/${encodeURIComponent(projectIdentifier)}`))
    return { variant: "success", message: `Project: ${payload.name ?? projectIdentifier} (${Array.isArray(payload.tasks) ? payload.tasks.length : 0} tasks)` }
  }

  if (command.kind === "project_delete") {
    const projectIdentifier = requireArg(command.projectIdentifier, "/project delete <project-id>")
    if (!projectIdentifier) return usage("/project delete <project-id>")
    const payload = objectPayload(
      await fetchJson(fetch, baseUrl, `/api/v1/projects/${encodeURIComponent(projectIdentifier)}`, { method: "DELETE" }),
    )
    return { variant: "success", message: String(payload.message ?? `Project deleted: ${projectIdentifier}`) }
  }

  if (command.kind === "project_start") {
    const projectIdentifier = requireArg(command.projectIdentifier, "/project start <project-id-or-name>")
    if (!projectIdentifier) return usage("/project start <project-id-or-name>")
    const payload = objectPayload(
      await fetchJson(fetch, baseUrl, "/api/v1/projects/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_identifier: projectIdentifier,
          continuous: true,
          session_id: sessionID,
          directory,
        }),
      }),
    )
    return { variant: "success", message: `Project started: ${objectPayload(payload.project).name ?? projectIdentifier}` }
  }

  if (command.kind === "task_create") {
    const projectId = requireArg(command.projectId, "/task create <project-id> <title>")
    const title = requireArg(command.title, "/task create <project-id> <title>")
    if (!projectId || !title) return usage("/task create <project-id> <title>")
    const payload = objectPayload(
      await fetchJson(fetch, baseUrl, "/api/v1/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          title,
          description: command.description,
          parent_task_id: command.parentTaskId,
          priority: command.priority,
        }),
      }),
    )
    return { variant: "success", message: `Task created: ${payload.title ?? title}` }
  }

  if (command.kind === "task_list") {
    const url = new URL("/api/v1/tasks", baseUrl)
    if (command.projectId) url.searchParams.set("project_id", command.projectId)
    if (command.status) url.searchParams.set("status", command.status)
    const response = await fetch(url)
    if (!response.ok) throw new Error(await response.text().catch(() => "task list failed"))
    const payload = objectPayload(await response.json())
    return { variant: "success", message: `Tasks: ${Array.isArray(payload.tasks) ? payload.tasks.length : 0}` }
  }

  if (command.kind === "task_show") {
    const taskId = requireArg(command.taskId, "/task show <task-id>")
    if (!taskId) return usage("/task show <task-id>")
    const payload = objectPayload(await fetchJson(fetch, baseUrl, `/api/v1/tasks/${encodeURIComponent(taskId)}`))
    return { variant: "success", message: `Task: ${payload.title ?? taskId} (${payload.status ?? "unknown"})` }
  }

  if (command.kind === "task_start") {
    const taskId = requireArg(command.taskId, "/task start <task-id>")
    if (!taskId) return usage("/task start <task-id>")
    const payload = objectPayload(await fetchJson(fetch, baseUrl, `/api/v1/tasks/${encodeURIComponent(taskId)}/start`, { method: "POST" }))
    return { variant: "success", message: String(payload.message ?? `Task started: ${taskId}`) }
  }

  if (command.kind === "task_complete") {
    const taskId = requireArg(command.taskId, "/task complete <task-id>")
    if (!taskId) return usage("/task complete <task-id>")
    const payload = objectPayload(await fetchJson(fetch, baseUrl, `/api/v1/tasks/${encodeURIComponent(taskId)}/complete`, { method: "POST" }))
    return { variant: "success", message: String(payload.message ?? `Task completed: ${taskId}`) }
  }

  if (command.kind === "task_execute") {
    const taskId = requireArg(command.taskId, "/task execute <task-id>")
    if (!taskId) return usage("/task execute <task-id>")
    const payload = objectPayload(
      await fetchJson(fetch, baseUrl, `/api/v1/tasks/${encodeURIComponent(taskId)}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionID, directory }),
      }),
    )
    return { variant: "success", message: `Task execution started: ${objectPayload(payload.task).title ?? taskId}` }
  }

  if (command.kind === "task_delete") {
    const taskId = requireArg(command.taskId, "/task delete <task-id>")
    if (!taskId) return usage("/task delete <task-id>")
    const payload = objectPayload(await fetchJson(fetch, baseUrl, `/api/v1/tasks/${encodeURIComponent(taskId)}`, { method: "DELETE" }))
    return { variant: "success", message: String(payload.message ?? `Task deleted: ${taskId}`) }
  }

  const taskId = requireArg(command.taskId, "/task resume <task-id> <answer>")
  const answer = requireArg(command.answer, "/task resume <task-id> <answer>")
  if (!taskId || !answer) return usage("/task resume <task-id> <answer>")
  const payload = objectPayload(
    await fetchJson(fetch, baseUrl, `/api/v1/tasks/${encodeURIComponent(taskId)}/clarification/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer, answered_by: "tui", session_id: sessionID, directory }),
    }),
  )
  return { variant: "success", message: `Clarification resumed: ${objectPayload(payload.task).title ?? taskId}` }
}
