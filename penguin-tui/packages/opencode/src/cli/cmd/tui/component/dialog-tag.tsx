import { createEffect, createMemo, createResource, onCleanup } from "solid-js"
import { DialogSelect } from "@tui/ui/dialog-select"
import { useDialog } from "@tui/ui/dialog"
import { useSDK } from "@tui/context/sdk"
import { useSync } from "@tui/context/sync"
import { createStore } from "solid-js/store"
import { createDebouncedSignal } from "@tui/util/signal"

export function DialogTag(props: { onSelect?: (value: string) => void }) {
  const sdk = useSDK()
  const sync = useSync()
  const dialog = useDialog()

  const [store] = createStore({
    filter: "",
  })

  const [fileQuery, setFileQuery] = createDebouncedSignal("", 35)
  let fileSearchAbort: AbortController | undefined
  createEffect(() => {
    const query = store.filter
    fileSearchAbort?.abort()
    setFileQuery(query)
  })
  onCleanup(() => fileSearchAbort?.abort())

  const [files] = createResource(fileQuery, async (query) => {
    fileSearchAbort?.abort()
    const abort = new AbortController()
    fileSearchAbort = abort
    const params = {
      query,
      directory: sdk.sessionID ? (sync.session.get(sdk.sessionID)?.directory ?? sdk.directory) : sdk.directory,
      session_id: sdk.sessionID,
      signal: abort.signal,
    } as Parameters<typeof sdk.client.find.files>[0] & {
      session_id?: string
    }
    const result = await sdk.client.find.files(params).catch((error) => {
      if (abort.signal.aborted) return undefined
      throw error
    })
    if (abort.signal.aborted) return []
    if (!result) return []
    if (result.error) return []
    const sliced = (result.data ?? []).slice(0, 5)
    return sliced
  })

  const options = createMemo(() =>
    (files() ?? []).map((file) => ({
      value: file,
      title: file,
    })),
  )

  return (
    <DialogSelect
      title="Autocomplete"
      options={options()}
      onSelect={(option) => {
        props.onSelect?.(option.value)
        dialog.clear()
      }}
    />
  )
}
