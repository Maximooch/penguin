export type PenguinLocalCommand =
  | { kind: "config" }
  | { kind: "settings" }
  | { kind: "tool_details" }
  | { kind: "thinking" }
  | {
      kind: "project_create"
      projectName?: string
      description?: string
      workspacePath?: string
    }
  | {
      kind: "project_init"
      projectName?: string
      blueprintPath?: string
      workspacePath?: string
    }
  | {
      kind: "project_list"
    }
  | {
      kind: "project_show"
      projectIdentifier?: string
    }
  | {
      kind: "project_delete"
      projectIdentifier?: string
    }
  | {
      kind: "project_start"
      projectIdentifier?: string
    }
  | {
      kind: "task_create"
      projectId?: string
      title?: string
      description?: string
      parentTaskId?: string
      priority?: number
    }
  | {
      kind: "task_list"
      projectId?: string
      status?: string
    }
  | {
      kind: "task_show"
      taskId?: string
    }
  | {
      kind: "task_start"
      taskId?: string
    }
  | {
      kind: "task_complete"
      taskId?: string
    }
  | {
      kind: "task_execute"
      taskId?: string
    }
  | {
      kind: "task_delete"
      taskId?: string
    }
  | {
      kind: "task_clarification_resume"
      taskId?: string
      answer?: string
    }

export type PenguinPromptClassification =
  | {
      kind: "local_command"
      command: PenguinLocalCommand
    }
  | {
      kind: "chat"
    }

function splitArgs(input: string): string[] {
  return input.match(/(?:[^\s"]+|"[^"]*")+/g)?.map((part) => part.replace(/^"|"$/g, "")) ?? []
}

function optionValue(args: string[], name: string): string | undefined {
  const index = args.indexOf(name)
  if (index < 0) return undefined
  return args[index + 1]
}

function withoutOptions(args: string[], optionNames: string[]): string[] {
  const result: string[] = []
  for (let index = 0; index < args.length; index++) {
    const arg = args[index]
    if (optionNames.includes(arg)) {
      index++
      continue
    }
    result.push(arg)
  }
  return result
}

function parsePriority(value: string | undefined): number | undefined {
  if (!value) return undefined
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) ? parsed : undefined
}

function parseProjectInit(args: string[]): PenguinLocalCommand {
  const projectName = withoutOptions(args, ["--blueprint", "--workspace"])[0]
  return {
    kind: "project_init",
    projectName,
    blueprintPath: optionValue(args, "--blueprint"),
    workspacePath: optionValue(args, "--workspace"),
  }
}

function parseProjectCreate(args: string[]): PenguinLocalCommand {
  const projectName = withoutOptions(args, ["--description", "--workspace"])[0]
  return {
    kind: "project_create",
    projectName,
    description: optionValue(args, "--description"),
    workspacePath: optionValue(args, "--workspace"),
  }
}

function parseTaskCreate(args: string[]): PenguinLocalCommand {
  const positional = withoutOptions(args, ["--description", "--parent", "--priority"])
  return {
    kind: "task_create",
    projectId: positional[0],
    title: positional[1],
    description: optionValue(args, "--description"),
    parentTaskId: optionValue(args, "--parent"),
    priority: parsePriority(optionValue(args, "--priority")),
  }
}

function parseTaskList(args: string[]): PenguinLocalCommand {
  const positional = withoutOptions(args, ["--status"])
  return {
    kind: "task_list",
    projectId: positional[0],
    status: optionValue(args, "--status"),
  }
}

export function parsePenguinLocalCommand(inputText: string): PenguinLocalCommand | null {
  const firstLine = inputText.split("\n", 1)[0]?.trim() ?? ""
  if (!firstLine.startsWith("/")) return null

  const tokens = splitArgs(firstLine)
  if (tokens.length === 0) return null

  const head = tokens[0]
  if (!head.startsWith("/")) return null
  const command = head.slice(1)

  if (command === "config") return { kind: "config" }
  if (command === "settings") return { kind: "settings" }
  if (command === "tool_details") return { kind: "tool_details" }
  if (command === "thinking") return { kind: "thinking" }

  if (command === "project-create") return parseProjectCreate(tokens.slice(1))
  if (command === "project-init") return parseProjectInit(tokens.slice(1))
  if (command === "project-list") return { kind: "project_list" }
  if (command === "project-show" || command === "project-get") {
    return { kind: "project_show", projectIdentifier: tokens.slice(1).join(" ").trim() || undefined }
  }
  if (command === "project-delete") {
    return { kind: "project_delete", projectIdentifier: tokens.slice(1).join(" ").trim() || undefined }
  }
  if (command === "project-start") {
    return { kind: "project_start", projectIdentifier: tokens.slice(1).join(" ").trim() || undefined }
  }

  if (command === "task-create") return parseTaskCreate(tokens.slice(1))
  if (command === "task-list") return parseTaskList(tokens.slice(1))
  if (command === "task-show" || command === "task-get") return { kind: "task_show", taskId: tokens[1] }
  if (command === "task-start") return { kind: "task_start", taskId: tokens[1] }
  if (command === "task-complete") return { kind: "task_complete", taskId: tokens[1] }
  if (command === "task-execute") return { kind: "task_execute", taskId: tokens[1] }
  if (command === "task-delete") return { kind: "task_delete", taskId: tokens[1] }

  if (command === "project") {
    const subcommand = tokens[1]
    const args = tokens.slice(2)
    if (subcommand === "create") return parseProjectCreate(args)
    if (subcommand === "init") return parseProjectInit(args)
    if (subcommand === "list") return { kind: "project_list" }
    if (subcommand === "show" || subcommand === "get") {
      return { kind: "project_show", projectIdentifier: args.join(" ").trim() || undefined }
    }
    if (subcommand === "delete") {
      return { kind: "project_delete", projectIdentifier: args.join(" ").trim() || undefined }
    }
    if (subcommand === "start") {
      return { kind: "project_start", projectIdentifier: args.join(" ").trim() || undefined }
    }
    // `project run` is intentionally deferred until its cross-surface contract is repaired.
  }

  if (command === "task") {
    const subcommand = tokens[1]
    const args = tokens.slice(2)
    if (subcommand === "create") return parseTaskCreate(args)
    if (subcommand === "list") return parseTaskList(args)
    if (subcommand === "show" || subcommand === "get") return { kind: "task_show", taskId: args[0] }
    if (subcommand === "start") return { kind: "task_start", taskId: args[0] }
    if (subcommand === "complete") return { kind: "task_complete", taskId: args[0] }
    if (subcommand === "execute") return { kind: "task_execute", taskId: args[0] }
    if (subcommand === "delete") return { kind: "task_delete", taskId: args[0] }
    if (subcommand === "resume") {
      return {
        kind: "task_clarification_resume",
        taskId: args[0],
        answer: args.slice(1).join(" ").trim() || undefined,
      }
    }
    if (subcommand === "clarification" && args[0] === "resume") {
      return {
        kind: "task_clarification_resume",
        taskId: args[1],
        answer: args.slice(2).join(" ").trim() || undefined,
      }
    }
  }

  return null
}

export function classifyPenguinPromptInput(inputText: string): PenguinPromptClassification {
  const command = parsePenguinLocalCommand(inputText)
  if (command) {
    return {
      kind: "local_command",
      command,
    }
  }

  return {
    kind: "chat",
  }
}

export function shouldBootstrapPenguinSession(options: {
  propsSessionID?: string
  sdkSessionID?: string
  classification: PenguinPromptClassification
}): boolean {
  if (options.classification.kind === "local_command") return false
  if (options.propsSessionID) return false
  if (options.sdkSessionID) return false
  return true
}

export function shouldNavigateAfterPenguinSubmit(options: {
  propsSessionID?: string
  classification: PenguinPromptClassification
}): boolean {
  if (options.classification.kind === "local_command") return false
  return !options.propsSessionID
}
