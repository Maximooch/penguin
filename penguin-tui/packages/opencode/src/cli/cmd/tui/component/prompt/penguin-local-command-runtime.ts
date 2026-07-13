import type { PenguinLocalCommand } from "./penguin-local-command"
import { emitPenguinOptimisticPrompt } from "./penguin-send"
import { PenguinGoalSchema } from "../../context/sync-bootstrap"
import { summarizeSessionGoal } from "../../routes/session/goal-summary"

type GoalSetCommand = Extract<PenguinLocalCommand, { kind: "goal_set" }>
type GoalPromptOptions = Omit<Parameters<typeof emitPenguinOptimisticPrompt>[0], "text"> & {
  command: GoalSetCommand
}

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
  | { kind: "goal_status" }
  | { kind: "goal_set" }
  | { kind: "goal_pause" }
  | { kind: "goal_resume" }
  | { kind: "goal_run" }
  | { kind: "goal_clear" }
>

export type PenguinLocalCommandFetch = (input: URL, init?: RequestInit) => Promise<Response>

export type PenguinCommandResult = {
  variant: "success" | "warning"
  message: string
  cancelled?: boolean
}

export function emitPenguinOptimisticGoal(options: GoalPromptOptions): string {
  emitPenguinOptimisticPrompt({
    agentName: options.agentName,
    emit: options.emit,
    messageID: options.messageID,
    model: options.model,
    now: options.now,
    partID: options.partID,
    sessionID: options.sessionID,
    text: options.command.displayCommand,
  })
  return options.messageID
}

export function shouldEmitPenguinOptimisticGoal(command: PenguinLocalCommand): command is GoalSetCommand {
  return command.kind === "goal_set" && command.objective.trim().length > 0
}

export function penguinHttpLocalCommandNeedsSession(command: PenguinLocalCommand): boolean {
  return (
    command.kind === "project_start" ||
    command.kind === "task_execute" ||
    command.kind === "task_clarification_resume" ||
    command.kind.startsWith("goal_")
  )
}

export function isPenguinHttpLocalCommand(command: PenguinLocalCommand): command is PenguinHttpCommand {
  return command.kind.startsWith("project_") || command.kind.startsWith("task_") || command.kind.startsWith("goal_")
}

function requireArg(value: string | undefined, usage: string): string | undefined {
  return value || undefined
}

function usage(message: string): PenguinCommandResult {
  return { variant: "warning", message: `Usage: ${message}` }
}

class PenguinHttpCommandError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly code?: string,
  ) {
    super(message)
    this.name = "PenguinHttpCommandError"
  }
}

async function fetchJson(
  fetcher: PenguinLocalCommandFetch,
  baseUrl: string | URL,
  path: string,
  init?: RequestInit,
): Promise<unknown> {
  const response = await fetcher(new URL(path, baseUrl), init)
  if (!response.ok) {
    const rawDetail = await response.text().catch(() => `${path} failed`)
    let detail = rawDetail
    let code: string | undefined
    try {
      const body = objectPayload(JSON.parse(rawDetail))
      const structuredDetail = objectPayload(body.detail)
      const rawCode = structuredDetail.code ?? body.code
      const rawMessage = structuredDetail.message ?? body.message ?? body.detail
      if (typeof rawCode === "string" && rawCode) code = rawCode
      if (typeof rawMessage === "string" && rawMessage) detail = rawMessage
    } catch {}
    throw new PenguinHttpCommandError(response.status, detail, code)
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
  clientMessageID?: string
  clientPartID?: string
  confirmGoalReplace?: (objective: string) => Promise<boolean>
  directory: string
  sessionID?: string
}): Promise<PenguinCommandResult> {
  const { command, fetch, baseUrl, directory, sessionID } = options

  if (command.kind.startsWith("goal_")) {
    if (!sessionID) return usage("/goal <objective>|status|pause|resume|run|clear")
    const goalPath = `/api/v1/session/${encodeURIComponent(sessionID)}/goal`

    if (command.kind === "goal_status") {
      const payload = objectPayload(await fetchJson(fetch, baseUrl, goalPath))
      const goal = objectPayload(payload.goal)
      if (!payload.goal) return { variant: "success", message: "No session goal is set" }
      const parsed = PenguinGoalSchema.safeParse(payload.goal)
      if (parsed.success) {
        const summary = summarizeSessionGoal(parsed.data)
        return {
          variant: "success",
          message: `Goal: ${summary.status} — ${summary.objective} (${summary.tokens})`,
        }
      }
      return { variant: "success", message: `Goal: ${goal.status ?? "unknown"} — ${goal.objective ?? ""}` }
    }

    if (command.kind === "goal_clear") {
      await fetchJson(fetch, baseUrl, goalPath, { method: "DELETE" })
      return { variant: "success", message: "Session goal cleared" }
    }

    if (command.kind === "goal_pause") {
      const payload = objectPayload(
        await fetchJson(fetch, baseUrl, goalPath, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: "paused" }),
        }),
      )
      const goal = objectPayload(payload.goal)
      return { variant: "success", message: `Goal paused: ${goal.objective ?? "session goal"}` }
    }

    const runGoal = async () => {
      const payload = objectPayload(
        await fetchJson(fetch, baseUrl, `${goalPath}/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ directory }),
        }),
      )
      const goal = objectPayload(payload.goal)
      return {
        variant: "success" as const,
        message: `Goal ${goal.status ?? payload.status ?? "updated"}: ${goal.objective ?? "session goal"}`,
      }
    }

    if (command.kind === "goal_run") return runGoal()

    if (command.kind === "goal_resume") {
      await fetchJson(fetch, baseUrl, goalPath, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "active" }),
      })
      return runGoal()
    }

    if (command.kind !== "goal_set") return usage("/goal <objective>|status|pause|resume|run|clear")
    if (!command.objective) return usage("/goal <objective> [--replace]")
    const setGoal = async (replace: boolean, displayCommand: string) => {
      const displayMessage = options.clientMessageID
        ? {
            display_command: displayCommand,
            client_message_id: options.clientMessageID,
            ...(options.clientPartID ? { client_part_id: options.clientPartID } : {}),
          }
        : {}
      await fetchJson(fetch, baseUrl, goalPath, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          objective: command.objective,
          replace,
          ...displayMessage,
        }),
      })
    }
    try {
      await setGoal(command.replace, command.displayCommand)
    } catch (error) {
      const replacementConflict =
        !command.replace &&
        error instanceof PenguinHttpCommandError &&
        error.status === 409 &&
        error.code === "goal_replace_required"
      if (!replacementConflict || !options.confirmGoalReplace) throw error
      const confirmed = await options.confirmGoalReplace(command.objective)
      if (!confirmed) {
        return {
          variant: "warning",
          message: "Goal replacement cancelled",
          cancelled: true,
        }
      }
      await setGoal(true, `${command.displayCommand} --replace`)
    }
    try {
      return await runGoal()
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error)
      return {
        variant: "warning",
        message: `Goal saved, but its run did not start: ${detail}`,
      }
    }
  }

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

  if (command.kind !== "task_clarification_resume") return usage("/task resume <task-id> <answer>")
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
