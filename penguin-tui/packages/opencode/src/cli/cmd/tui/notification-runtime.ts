import {
  notificationPayloads,
  type AttentionEvent,
  type NotificationPayload,
  type NotificationPolicy,
} from "./notification-policy"

type SyncEvent = {
  type: string
  properties?: Record<string, unknown>
}

export type NotificationDeliveryOptions = {
  write?: (text: string) => void
  log?: (payload: NotificationPayload) => void
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined
}

export function attentionEventFromSyncEvent(event: SyncEvent): AttentionEvent | undefined {
  const properties = event.properties ?? {}
  const sessionID = stringValue(properties.sessionID)
  if (event.type === "permission.asked") {
    return {
      category: "approval_waiting",
      sessionID,
      title: "Penguin needs approval",
      message: stringValue(properties.title) ?? stringValue(properties.reason),
    }
  }
  if (event.type === "question.asked") {
    return {
      category: "question_waiting",
      sessionID,
      title: "Penguin has a question",
      message: stringValue(properties.question) ?? stringValue(properties.message),
    }
  }
  if (event.type === "session.error") {
    return {
      category: "run_failed",
      sessionID,
      title: "Penguin run failed",
      message: stringValue(properties.error) ?? stringValue(properties.message),
    }
  }
  return
}

export function notificationEventKey(event: SyncEvent): string | undefined {
  const properties = event.properties ?? {}
  const sessionID = stringValue(properties.sessionID) ?? ""
  const id =
    stringValue(properties.id) ??
    stringValue(properties.requestID) ??
    stringValue(properties.messageID) ??
    stringValue(properties.partID)
  if (!id) return
  return `${event.type}:${sessionID}:${id}`
}

export function notificationEscape(payload: NotificationPayload): string | undefined {
  if (payload.channel === "bell") return "\u0007"
  if (payload.channel === "osc") {
    const title = payload.title.replace(/[;\u0007]/g, " ")
    const body = payload.body.replace(/[;\u0007]/g, " ")
    return `\u001b]9;${title};${body}\u0007`
  }
  return
}

export function deliverNotificationPayloads(
  payloads: NotificationPayload[],
  options: NotificationDeliveryOptions = {},
): NotificationPayload[] {
  for (const payload of payloads) {
    const escape = notificationEscape(payload)
    if (escape && options.write) options.write(escape)
    if (!escape && options.log) options.log(payload)
  }
  return payloads
}

export function notifyForSyncEvent(
  event: SyncEvent,
  policy: NotificationPolicy,
  options: NotificationDeliveryOptions = {},
): NotificationPayload[] {
  const attention = attentionEventFromSyncEvent(event)
  if (!attention) return []
  return deliverNotificationPayloads(notificationPayloads(attention, policy), options)
}
