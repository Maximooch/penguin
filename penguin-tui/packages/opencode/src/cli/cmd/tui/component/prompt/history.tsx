import path from "path"
import { Global } from "@/global"
import { onMount } from "solid-js"
import { createStore, produce } from "solid-js/store"
import { createSimpleContext } from "../../context/helper"
import { appendFile, writeFile } from "fs/promises"
import {
  appendPromptHistory,
  emptyPrompt,
  movePromptHistory,
  normalizePromptHistory,
  type PromptInfo,
} from "./history-state"

export type { PromptHistoryBrowseState, PromptInfo } from "./history-state"

export const { use: usePromptHistory, provider: PromptHistoryProvider } = createSimpleContext({
  name: "PromptHistory",
  init: () => {
    const historyFile = Bun.file(path.join(Global.Path.state, "prompt-history.jsonl"))
    onMount(async () => {
      const text = await historyFile.text().catch(() => "")
      const parsed = text
        .split("\n")
        .filter(Boolean)
        .map((line) => {
          try {
            return JSON.parse(line)
          } catch {
            return null
          }
        })
        .filter((line): line is PromptInfo => line !== null)
      const lines = normalizePromptHistory(parsed)

      setStore({
        draft: emptyPrompt(),
        history: lines,
        index: null,
      })

      // Rewrite file with only valid entries to self-heal corruption
      if (lines.length > 0) {
        const content = lines.map((line) => JSON.stringify(line)).join("\n") + "\n"
        writeFile(historyFile.name!, content).catch(() => {})
      }
    })

    const [store, setStore] = createStore({
      draft: emptyPrompt(),
      history: [] as PromptInfo[],
      index: null as number | null,
    })

    return {
      move(direction: 1 | -1, prompt: PromptInfo) {
        const result = movePromptHistory(
          {
            draft: store.draft,
            history: store.history,
            index: store.index,
          },
          direction,
          prompt,
        )
        setStore({
          draft: result.state.draft,
          history: result.state.history,
          index: result.state.index,
        })
        return result.prompt
      },
      append(item: PromptInfo) {
        const history = appendPromptHistory(store.history, item)
        if (history === store.history) {
          setStore({
            draft: emptyPrompt(),
            index: null,
          })
          return
        }

        const trimmed = history.length < store.history.length + 1
        setStore(
          produce((draft) => {
            draft.draft = emptyPrompt()
            draft.history = history
            draft.index = null
          }),
        )

        if (trimmed) {
          const content = store.history.map((line) => JSON.stringify(line)).join("\n") + "\n"
          writeFile(historyFile.name!, content).catch(() => {})
          return
        }

        appendFile(historyFile.name!, JSON.stringify(history[history.length - 1]) + "\n").catch(() => {})
      },
    }
  },
})
