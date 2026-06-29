import { TextAttributes } from "@opentui/core"
import { DialogSelect, type DialogSelectOption } from "@tui/ui/dialog-select"
import { useSDK } from "@tui/context/sdk"
import { useSync } from "@tui/context/sync"
import { useKV } from "@tui/context/kv"
import { useToast } from "@tui/ui/toast"
import { useDialog } from "@tui/ui/dialog"
import { DialogPrompt } from "@tui/ui/dialog-prompt"
import { Log } from "@/util/log"
import { createMemo } from "solid-js"
import { useTheme } from "../context/theme"
import {
  NOTIFICATION_MODES,
  SOUND_PACKS,
  normalizeNotificationPolicy,
  notificationPayloads,
  type NotificationMode,
  type NotificationPolicy,
  type SoundPack,
} from "../notification-policy"
import { deliverNotificationPayloads } from "../notification-runtime"
import {
  NOTIFICATION_POLICY_OVERRIDE_KEY,
  notificationPolicySummary,
  parseQuietHoursInput,
  withNotificationDetails,
  withNotificationMode,
  withNotificationQuietHours,
  withNotificationSoundPack,
} from "../notification-settings"

type NotificationOption = DialogSelectOption<string>

const MODE_LABELS: Record<NotificationMode, string> = {
  off: "Off",
  visual: "Visual log",
  bell: "Terminal bell",
  osc: "OSC notification",
  os: "Desktop notification",
  terminal: "Terminal app notification",
  sound: "Sound",
  combined: "Desktop + sound",
}

const MODE_DESCRIPTIONS: Partial<Record<NotificationMode, string>> = {
  visual: "In-TUI log only; no desktop banner or sound",
  bell: "Uses the terminal bell; depends on terminal settings",
  osc: "Uses OSC 9; supported terminals may show a desktop banner",
  os: "Uses native desktop notifications on macOS, Linux, and Windows",
  terminal: "Uses terminal notification escape sequences; supported terminals may show a desktop banner",
  sound: "Plays a native system sound without showing a desktop banner",
  combined: "Shows a desktop notification and plays the selected sound",
}

const SOUND_LABELS: Record<SoundPack, string> = {
  generic: "Generic",
  train_station: "Train station",
  penguin: "Penguin / NOOT NOOT",
}

export function DialogNotifications() {
  const { theme } = useTheme()
  const dialog = useDialog()
  const sdk = useSDK()
  const sync = useSync()
  const kv = useKV()
  const toast = useToast()

  const policy = createMemo(() => normalizeNotificationPolicy(sync.data.notification_policy))

  const applyPolicy = (next: NotificationPolicy, message: string) => {
    const normalized = normalizeNotificationPolicy(next)
    kv.set(NOTIFICATION_POLICY_OVERRIDE_KEY, normalized)
    sync.set("notification_policy", normalized)
    toast.show({ variant: "info", message })
  }

  const reloadServerDefault = async () => {
    const result = await sdk
      .fetch(new URL("/api/v1/notifications/config", sdk.url))
      .then((res) => (res.ok ? res.json() : undefined))
      .catch(() => undefined)
    const normalized = normalizeNotificationPolicy(result)
    kv.set(NOTIFICATION_POLICY_OVERRIDE_KEY, undefined)
    sync.set("notification_policy", normalized)
    toast.show({ variant: "info", message: "Notification policy reset to server default" })
  }

  const testNotification = () => {
    const current = policy()
    const payloads = deliverNotificationPayloads(
      notificationPayloads(
        {
          category: "question_waiting",
          title: "Penguin notification test",
          message: "This is a test notification from the TUI settings modal.",
        },
        current,
      ),
      {
        write: (text) => process.stdout.write(text),
        log: (payload) =>
          Log.Default.info("penguin test notification", {
            category: payload.category,
            channel: payload.channel,
            sound: payload.sound,
            sessionID: payload.sessionID,
          }),
      },
    )

    if (payloads.length === 0) {
      toast.show({ variant: "info", message: "Notifications are disabled for the current mode" })
      return
    }

    toast.show({
      variant: "success",
      message: `Sent test notification via ${payloads.map((item) => item.channel).join(", ")}`,
    })
  }

  const setQuietHours = async () => {
    const current = policy()
    const value = await DialogPrompt.show(dialog, "Quiet hours", {
      placeholder: "22:00-07:00",
      value: current.quietHours ? `${current.quietHours.start}-${current.quietHours.end}` : "",
    })
    if (value === null) return
    const quietHours = parseQuietHoursInput(value)
    if (!quietHours) {
      toast.show({ variant: "error", message: "Use 24-hour format, for example 22:00-07:00" })
      dialog.replace(() => <DialogNotifications />)
      return
    }
    applyPolicy(
      withNotificationQuietHours(current, quietHours),
      `Quiet hours set to ${quietHours.start}-${quietHours.end}`,
    )
    dialog.replace(() => <DialogNotifications />)
  }

  const options = createMemo<NotificationOption[]>(() => {
    const current = policy()
    return [
      {
        title: "Send test notification",
        value: "test",
        category: "Test",
        description: notificationPolicySummary(current),
        onSelect: testNotification,
      },
      ...NOTIFICATION_MODES.map(
        (mode): NotificationOption => ({
          title: `${current.mode === mode ? "●" : "○"} ${MODE_LABELS[mode]}`,
          value: `mode:${mode}`,
          category: "Mode",
          description: MODE_DESCRIPTIONS[mode],
          onSelect: () =>
            applyPolicy(withNotificationMode(current, mode), `Notification mode set to ${MODE_LABELS[mode]}`),
        }),
      ),
      ...SOUND_PACKS.map(
        (soundPack): NotificationOption => ({
          title: `${(current.soundPack ?? "generic") === soundPack ? "●" : "○"} ${SOUND_LABELS[soundPack]}`,
          value: `sound:${soundPack}`,
          category: "Sound pack",
          description: "Used by Sound and Desktop + sound",
          onSelect: () =>
            applyPolicy(
              withNotificationSoundPack(current, soundPack),
              `Notification sound pack set to ${SOUND_LABELS[soundPack]}`,
            ),
        }),
      ),
      {
        title: current.includeDetails ? "Disable notification details" : "Enable notification details",
        value: "details",
        category: "Privacy",
        description: "Details are sanitized before delivery",
        onSelect: () =>
          applyPolicy(
            withNotificationDetails(current, !current.includeDetails),
            current.includeDetails ? "Notification details disabled" : "Notification details enabled",
          ),
      },
      {
        title: current.quietHours
          ? `Quiet hours: ${current.quietHours.start}-${current.quietHours.end}`
          : "Set quiet hours",
        value: "quiet-hours",
        category: "Schedule",
        description: "Suppress notifications during this local time range",
        onSelect: setQuietHours,
      },
      {
        title: "Clear quiet hours",
        value: "quiet-hours.clear",
        category: "Schedule",
        onSelect: () => applyPolicy(withNotificationQuietHours(current, undefined), "Quiet hours cleared"),
      },
      {
        title: "Reset to server default",
        value: "reset",
        category: "Server",
        description: "Remove the local TUI override and reload backend defaults",
        onSelect: reloadServerDefault,
      },
    ]
  })

  return (
    <box paddingLeft={2} paddingRight={2} gap={1} paddingBottom={1}>
      <box flexDirection="row" justifyContent="space-between">
        <text fg={theme.text} attributes={TextAttributes.BOLD}>
          Notifications
        </text>
        <text fg={theme.textMuted}>esc</text>
      </box>
      <text fg={theme.textMuted} wrapMode="word">
        Configure local TUI notification behavior. Backend environment variables provide defaults; this dialog stores a
        local override.
      </text>
      <DialogSelect title="Notification settings" options={options()} />
    </box>
  )
}
