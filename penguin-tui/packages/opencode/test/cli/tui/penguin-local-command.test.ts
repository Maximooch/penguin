import { describe, expect, test } from "bun:test"

import {
  classifyPenguinPromptInput,
  parsePenguinLocalCommand,
  shouldBootstrapPenguinSession,
  shouldNavigateAfterPenguinSubmit,
} from "../../../src/cli/cmd/tui/component/prompt/penguin-local-command"

describe("penguin local command parser", () => {
  test("parses dashed project init form", () => {
    expect(parsePenguinLocalCommand('/project-init "Auth Rewrite" --blueprint ./auth.md')).toEqual({
      kind: "project_init",
      projectName: "Auth Rewrite",
      blueprintPath: "./auth.md",
    })
  })

  test("parses spaced project init form", () => {
    expect(parsePenguinLocalCommand('/project init "Auth Rewrite" --blueprint ./auth.md')).toEqual({
      kind: "project_init",
      projectName: "Auth Rewrite",
      blueprintPath: "./auth.md",
    })
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
    expect(classifyPenguinPromptInput('/project init Demo --blueprint ./demo.md')).toEqual({
      kind: "local_command",
      command: {
        kind: "project_init",
        projectName: "Demo",
        blueprintPath: "./demo.md",
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
