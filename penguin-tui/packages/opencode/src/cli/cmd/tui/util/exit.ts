import { DialogConfirm } from "@tui/ui/dialog-confirm"
import type { DialogContext } from "@tui/ui/dialog"

type ExitFn = () => Promise<void>

type SyncLike = {
  data: {
    session_status?: Record<string, { type?: string } | undefined>
  }
}

type SDKLike = {
  client: {
    session: {
      abort: (input: { sessionID: string }) => Promise<unknown>
    }
  }
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function waitForIdle(sync: SyncLike, sessionID: string) {
  const deadline = Date.now() + 2500
  while (Date.now() < deadline) {
    const state = sync.data.session_status?.[sessionID]
    if (!state || state.type === "idle") return
    await wait(50)
  }
}

export async function exitSession(options: {
  busy: boolean
  sessionID?: string
  dialog: DialogContext
  sdk: SDKLike
  sync: SyncLike
  exit: ExitFn
}) {
  if (!options.busy || !options.sessionID) {
    await options.exit()
    return
  }

  const confirmed = await DialogConfirm.show(
    options.dialog,
    "Interrupt And Exit?",
    "Penguin is still running. Interrupt the current session and exit the app?",
  )
  if (!confirmed) return

  await options.sdk.client.session.abort({ sessionID: options.sessionID }).catch(() => undefined)
  await waitForIdle(options.sync, options.sessionID)
  await options.exit()
}
