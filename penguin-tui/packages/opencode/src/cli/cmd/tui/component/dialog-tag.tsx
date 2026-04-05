import { createMemo, createResource } from "solid-js"
import { DialogSelect } from "@tui/ui/dialog-select"
import { useDialog } from "@tui/ui/dialog"
import { useSDK } from "@tui/context/sdk"
import { useSync } from "@tui/context/sync"
import { createStore } from "solid-js/store"

export function DialogTag(props: { onSelect?: (value: string) => void }) {
  const sdk = useSDK()
  const sync = useSync()
  const dialog = useDialog()

  const [store] = createStore({
    filter: "",
  })

  const [files] = createResource(
    () => [store.filter],
    async () => {
      const params = {
        query: store.filter,
        directory: sdk.sessionID
          ? sync.session.get(sdk.sessionID)?.directory ?? sdk.directory
          : sdk.directory,
        session_id: sdk.sessionID,
      } as Parameters<typeof sdk.client.find.files>[0] & {
        session_id?: string
      }
      const result = await sdk.client.find.files(params)
      if (result.error) return []
      const sliced = (result.data ?? []).slice(0, 5)
      return sliced
    },
  )

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
