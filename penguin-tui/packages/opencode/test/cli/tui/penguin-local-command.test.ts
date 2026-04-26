import { describe, expect, test } from "bun:test"

import {
  classifyPenguinPromptInput,
  parsePenguinLocalCommand,
  shouldBootstrapPenguinSession,
  shouldNavigateAfterPenguinSubmit,
} from "../../../src/cli/cmd/tui/component/prompt/penguin-local-command"

describe("penguin local command parser", () => {
  test("parses dashed project init form", () => {
    expect(parsePenguinLocalCommand('/project-init "Auth Rewrite" --blueprint ./auth.md --workspace ./auth-workspace')).toEqual({
      kind: "project_init",
      projectName: "Auth Rewrite",
      blueprintPath: "./auth.md",
      workspacePath: "./auth-workspace",
    })
  })

  test("parses spaced project init form", () => {
    expect(parsePenguinLocalCommand('/project init "Auth Rewrite" --blueprint ./auth.md --workspace ./auth-workspace')).toEqual({
      kind: "project_init",
      projectName: "Auth Rewrite",
      blueprintPath: "./auth.md",
      workspacePath: "./auth-workspace",
    })
  })

  test("parses project create/list/show/delete forms", () => {
    expect(parsePenguinLocalCommand('/project create "Auth Rewrite" --description "Rewrite auth" --workspace ./auth')).toEqual({
      kind: "project_create",
      projectName: "Auth Rewrite",
      description: "Rewrite auth",
      workspacePath: "./auth",
    })
    expect(parsePenguinLocalCommand('/project list')).toEqual({ kind: "project_list" })
    expect(parsePenguinLocalCommand('/project show project-1')).toEqual({ kind: "project_show", projectIdentifier: "project-1" })
    expect(parsePenguinLocalCommand('/project delete project-1')).toEqual({ kind: "project_delete", projectIdentifier: "project-1" })
  })

  test("parses dashed and spaced project start forms equivalently", () => {
    expect(parsePenguinLocalCommand('/project-start "Auth Rewrite"')).toEqual({
      kind: "project_start",
      projectIdentifier: "Auth Rewrite",
    })
    expect(parsePenguinLocalCommand('/project start "Auth Rewrite"')).toEqual({
      kind: "project_start",
      projectIdentifier: "Auth Rewrite",
    })
  })

  test("does not parse deferred project run command", () => {
    expect(parsePenguinLocalCommand('/project run ./blueprint.md')).toBeNull()
  })

  test("parses task command forms", () => {
    expect(parsePenguinLocalCommand('/task create project-1 "Write tests" --description "Add regression tests" --parent parent-1 --priority 3')).toEqual({
      kind: "task_create",
      projectId: "project-1",
      title: "Write tests",
      description: "Add regression tests",
      parentTaskId: "parent-1",
      priority: 3,
    })
    expect(parsePenguinLocalCommand('/task list project-1 --status active')).toEqual({
      kind: "task_list",
      projectId: "project-1",
      status: "active",
    })
    expect(parsePenguinLocalCommand('/task show task-1')).toEqual({ kind: "task_show", taskId: "task-1" })
    expect(parsePenguinLocalCommand('/task start task-1')).toEqual({ kind: "task_start", taskId: "task-1" })
    expect(parsePenguinLocalCommand('/task complete task-1')).toEqual({ kind: "task_complete", taskId: "task-1" })
    expect(parsePenguinLocalCommand('/task execute task-1')).toEqual({ kind: "task_execute", taskId: "task-1" })
    expect(parsePenguinLocalCommand('/task delete task-1')).toEqual({ kind: "task_delete", taskId: "task-1" })
    expect(parsePenguinLocalCommand('/task resume task-1 "Use Postgres"')).toEqual({
      kind: "task_clarification_resume",
      taskId: "task-1",
      answer: "Use Postgres",
    })
  })

  test("parses existing local commands", () => {
    expect(parsePenguinLocalCommand('/settings')).toEqual({ kind: "settings" })
    expect(parsePenguinLocalCommand('/config')).toEqual({ kind: "config" })
    expect(parsePenguinLocalCommand('/thinking')).toEqual({ kind: "thinking" })
    expect(parsePenguinLocalCommand('/tool_details')).toEqual({ kind: "tool_details" })
  })

  test("returns null for non-command input", () => {
    expect(parsePenguinLocalCommand('hello world')).toBeNull()
  })
})

describe("penguin prompt classification", () => {
  test("classifies project commands as local commands", () => {
    expect(classifyPenguinPromptInput('/project init Demo --blueprint ./demo.md --workspace ./demo-workspace')).toEqual({
      kind: "local_command",
      command: {
        kind: "project_init",
        projectName: "Demo",
        blueprintPath: "./demo.md",
        workspacePath: "./demo-workspace",
      },
    })
  })

  test("classifies task commands as local commands", () => {
    expect(classifyPenguinPromptInput('/task list project-1')).toEqual({
      kind: "local_command",
      command: {
        kind: "task_list",
        projectId: "project-1",
        status: undefined,
      },
    })
  })

  test("classifies non-command input as chat", () => {
    expect(classifyPenguinPromptInput('fix the failing test')).toEqual({ kind: "chat" })
  })

  test("does not bootstrap a session for home-screen local commands", () => {
    const classification = classifyPenguinPromptInput('/project start Demo')
    expect(shouldBootstrapPenguinSession({ classification })).toBe(false)
    expect(shouldNavigateAfterPenguinSubmit({ classification })).toBe(false)
  })

  test("does not bootstrap a session for local commands even when a session already exists", () => {
    const classification = classifyPenguinPromptInput('/settings')
    expect(shouldBootstrapPenguinSession({ classification, propsSessionID: 'ses_123' })).toBe(false)
    expect(shouldNavigateAfterPenguinSubmit({ classification, propsSessionID: 'ses_123' })).toBe(false)
  })

  test("bootstraps and navigates for home-screen chat prompts", () => {
    const classification = classifyPenguinPromptInput('build the feature')
    expect(shouldBootstrapPenguinSession({ classification })).toBe(true)
    expect(shouldNavigateAfterPenguinSubmit({ classification })).toBe(true)
  })

  test("does not bootstrap or navigate for chat prompts in an existing session", () => {
    const classification = classifyPenguinPromptInput('continue')
    expect(shouldBootstrapPenguinSession({ classification, propsSessionID: 'ses_123' })).toBe(false)
    expect(shouldNavigateAfterPenguinSubmit({ classification, propsSessionID: 'ses_123' })).toBe(false)
  })
})
