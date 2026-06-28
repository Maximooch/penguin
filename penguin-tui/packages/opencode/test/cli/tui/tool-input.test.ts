import { describe, expect, test } from "bun:test"
import {
  coerceToolInputRecord,
  formatPrimitiveToolInput,
  isToolInputRecord,
  stringifyToolInput,
} from "../../../src/cli/cmd/tui/util/tool-input"

describe("tool input formatting", () => {
  test("keeps object inputs as records", () => {
    const input = { command: "ls", timeout: 10 }

    expect(isToolInputRecord(input)).toBe(true)
    expect(coerceToolInputRecord(input)).toBe(input)
    expect(formatPrimitiveToolInput(input)).toBe("[command=ls, timeout=10]")
  })

  test("coerces primitive malformed inputs into a display record", () => {
    expect(coerceToolInputRecord("raw command")).toEqual({ value: "raw command" })
    expect(formatPrimitiveToolInput("raw command")).toBe("[value=raw command]")
  })

  test("does not treat arrays as tool input records", () => {
    expect(isToolInputRecord(["a"])).toBe(false)
    expect(coerceToolInputRecord(["a"])).toEqual({ value: ["a"] })
    expect(formatPrimitiveToolInput(["a"])).toBe("")
  })

  test("omits selected primitive keys", () => {
    expect(formatPrimitiveToolInput({ filePath: "app.py", replaceAll: true }, ["filePath"])).toBe("[replaceAll=true]")
  })

  test("stringifies circular and non-json values without throwing", () => {
    const input: Record<string, unknown> = {
      command: "inspect",
      count: 1n,
      marker: Symbol("tool"),
      callback: function retry() {},
    }
    input.self = input

    const result = stringifyToolInput(input)

    expect(result).toContain('"command": "inspect"')
    expect(result).toContain('"count": "1"')
    expect(result).toContain('"marker": "Symbol(tool)"')
    expect(result).toContain('"callback": "[Function retry]"')
    expect(result).toContain('"self": "[Circular]"')
  })
})
