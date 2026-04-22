import { describe, expect, test } from "bun:test"

describe("prompt project discoverability", () => {
  test("registers visible project command palette entries with slash aliases", async () => {
    const source = await Bun.file("src/cli/cmd/tui/component/prompt/index.tsx").text()

    expect(source).toContain('title: "Initialize project from Blueprint"')
    expect(source).toContain('value: "project.init.prefill"')
    expect(source).toContain('category: "Project"')
    expect(source).toContain('name: "project-init"')
    expect(source).toContain('aliases: ["project init"]')
    expect(source).toContain("prefillPrompt('/project init \"Project Name\" --blueprint ./blueprint.md')")

    expect(source).toContain('title: "Start project execution"')
    expect(source).toContain('value: "project.start.prefill"')
    expect(source).toContain('name: "project-start"')
    expect(source).toContain('aliases: ["project start"]')
    expect(source).toContain("prefillPrompt('/project start \"Project Name\"')")
  })
})
