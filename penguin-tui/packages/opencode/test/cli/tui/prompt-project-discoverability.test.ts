import { describe, expect, test } from "bun:test"

const PROJECT_COMMANDS = [
  ['title: "Create project"', 'name: "project-create"', 'aliases: ["project create"]'],
  ['title: "Initialize project from Blueprint"', 'name: "project-init"', 'aliases: ["project init"]'],
  ['title: "List projects"', 'name: "project-list"', 'aliases: ["project list"]'],
  ['title: "Show project"', 'name: "project-show"', 'aliases: ["project show", "project get"]'],
  ['title: "Start project execution"', 'name: "project-start"', 'aliases: ["project start"]'],
  ['title: "Delete project"', 'name: "project-delete"', 'aliases: ["project delete"]'],
]

const TASK_COMMANDS = [
  ['title: "Create task"', 'name: "task-create"', 'aliases: ["task create"]'],
  ['title: "List tasks"', 'name: "task-list"', 'aliases: ["task list"]'],
  ['title: "Show task"', 'name: "task-show"', 'aliases: ["task show", "task get"]'],
  ['title: "Start task"', 'name: "task-start"', 'aliases: ["task start"]'],
  ['title: "Complete task"', 'name: "task-complete"', 'aliases: ["task complete"]'],
  ['title: "Execute task"', 'name: "task-execute"', 'aliases: ["task execute"]'],
  ['title: "Delete task"', 'name: "task-delete"', 'aliases: ["task delete"]'],
  ['title: "Resume task clarification"', 'name: "task-resume"', 'aliases: ["task resume", "task clarification resume"]'],
]

describe("prompt project/task discoverability", () => {
  test("registers visible project command palette entries with slash aliases", async () => {
    const source = await Bun.file("src/cli/cmd/tui/component/prompt/index.tsx").text()

    expect(source).toContain('category: "Project"')
    for (const command of PROJECT_COMMANDS) {
      for (const expected of command) {
        expect(source).toContain(expected)
      }
    }
  })

  test("registers visible task command palette entries with slash aliases", async () => {
    const source = await Bun.file("src/cli/cmd/tui/component/prompt/index.tsx").text()

    expect(source).toContain('category: "Task"')
    for (const command of TASK_COMMANDS) {
      for (const expected of command) {
        expect(source).toContain(expected)
      }
    }
  })

  test("keeps project run out of the TUI command surface while deferred", async () => {
    const source = await Bun.file("src/cli/cmd/tui/component/prompt/index.tsx").text()

    expect(source).not.toContain('name: "project-run"')
    expect(source).not.toContain('aliases: ["project run"]')
  })
})
