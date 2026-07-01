import { Log } from "@/util/log"
import { createStore } from "solid-js/store"
import { onCleanup, onMount } from "solid-js"
import { createSimpleContext } from "./helper"
import {
  DISABLE_FOCUS_REPORTING,
  ENABLE_FOCUS_REPORTING,
  terminalFocusFromInput,
  type TerminalFocusState,
} from "./terminal-focus-state"

export const { use: useTerminalFocus, provider: TerminalFocusProvider } = createSimpleContext({
  name: "TerminalFocus",
  init: () => {
    const [store, setStore] = createStore<TerminalFocusState>({
      focused: true,
      supported: false,
    })

    function applyInput(input: Buffer | string) {
      const next = terminalFocusFromInput(input, store)
      if (next.focused === store.focused && next.supported === store.supported) return
      setStore(next)
      Log.Default.info("terminal focus changed", {
        focused: next.focused,
        supported: next.supported,
      })
    }

    onMount(() => {
      if (!process.stdin.isTTY) return
      process.stdout.write(ENABLE_FOCUS_REPORTING)
      process.stdin.on("data", applyInput)
      onCleanup(() => {
        process.stdin.removeListener("data", applyInput)
        process.stdout.write(DISABLE_FOCUS_REPORTING)
      })
    })

    return {
      get focused() {
        return store.focused
      },
      get supported() {
        return store.supported
      },
    }
  },
})
