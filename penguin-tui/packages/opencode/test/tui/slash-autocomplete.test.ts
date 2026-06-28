import { describe, expect, test } from "bun:test"
import { rankSlashAutocompleteOptions } from "../../src/cli/cmd/tui/component/prompt/slash-autocomplete"

describe("slash autocomplete ranking", () => {
  test("prefers models for /mo when several commands share the prefix", () => {
    const ranked = rankSlashAutocompleteOptions("mo", [
      { display: "/mode" },
      { display: "/model" },
      { display: "/models" },
      { display: "/move" },
    ])

    expect(ranked.map((item) => item.display)).toEqual(["/models", "/mode", "/model", "/move"])
  })

  test("uses aliases when ranking slash commands", () => {
    const ranked = rankSlashAutocompleteOptions("project list", [
      { display: "/project-create", aliases: ["/project create"] },
      { display: "/project-list", aliases: ["/project list"] },
    ])

    expect(ranked[0]?.display).toBe("/project-list")
  })

  test("ignores source labels on server command displays", () => {
    const ranked = rankSlashAutocompleteOptions("deploy", [
      { display: "/debug:mcp" },
      { display: "/deploy:mcp" },
      { display: "/describe:skill" },
    ])

    expect(ranked[0]?.display).toBe("/deploy:mcp")
  })
})
