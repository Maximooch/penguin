export type PenguinLocalCommand =
  | { kind: "config" }
  | { kind: "settings" }
  | { kind: "tool_details" }
  | { kind: "thinking" }
  | {
      kind: "project_init"
      projectName?: string
      blueprintPath?: string
    }
  | {
      kind: "project_start"
      projectIdentifier?: string
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

  if (command === "project-init") {
    const [, ...args] = tokens
    const projectName = args[0]
    const blueprintIndex = args.indexOf("--blueprint")
    const blueprintPath = blueprintIndex >= 0 ? args[blueprintIndex + 1] : undefined
    return { kind: "project_init", projectName, blueprintPath }
  }

  if (command === "project-start") {
    const [, ...args] = tokens
    return { kind: "project_start", projectIdentifier: args.join(" ").trim() || undefined }
  }

  if (command === "project") {
    const subcommand = tokens[1]
    if (subcommand === "init") {
      const args = tokens.slice(2)
      const projectName = args[0]
      const blueprintIndex = args.indexOf("--blueprint")
      const blueprintPath = blueprintIndex >= 0 ? args[blueprintIndex + 1] : undefined
      return { kind: "project_init", projectName, blueprintPath }
    }

    if (subcommand === "start") {
      const args = tokens.slice(2)
      return { kind: "project_start", projectIdentifier: args.join(" ").trim() || undefined }
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
