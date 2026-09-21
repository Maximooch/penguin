import { createSignal, onMount } from "solid-js"
import { useSDK } from "@tui/context/sdk"
import { DialogSelect } from "@tui/ui/dialog-select"
import { useDialog } from "@tui/ui/dialog"
import { useToast } from "@tui/ui/toast"
import type { AccessMode } from "@tui/context/session-access"

export function DialogPermissions(props: { sessionID: string }) {
  const sdk = useSDK()
  const dialog = useDialog()
  const toast = useToast()
  const [busy, setBusy] = createSignal(false)
  const [ready, setReady] = createSignal(false)

  onMount(() => {
    sdk.access
      .load(props.sessionID)
      .then(() => setReady(true))
      .catch((error: Error) => {
        toast.show({ message: error.message, variant: "error" })
      })
  })

  return (
    <DialogSelect<AccessMode>
      title="Session permissions"
      current={sdk.access.get(props.sessionID)}
      options={[
        {
          title: "Ask for approval",
          value: "workspace",
          description: "Ask before editing external files. Clear remembered approvals.",
          disabled: !ready() || busy(),
        },
        {
          title: "Full access",
          value: "full_access",
          description: "Allow files, commands and network for this session. Resets on backend restart.",
          disabled: !ready() || busy(),
        },
      ]}
      onSelect={async (option) => {
        if (busy()) return
        setBusy(true)
        await sdk.access
          .set(props.sessionID, option.value)
          .then(() => {
            toast.show({ message: `Session permissions: ${option.title}`, variant: "success" })
            dialog.clear()
          })
          .catch((error: Error) => {
            toast.show({ message: error.message, variant: "error" })
          })
          .finally(() => setBusy(false))
      }}
    />
  )
}
