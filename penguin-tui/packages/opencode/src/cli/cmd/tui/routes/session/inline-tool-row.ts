const DENIED_ERROR_MARKERS = ["rejected permission", "specified a rule", "user dismissed"] as const

export type InlineToolState = {
  denied: boolean
  failed: boolean
  clickable: boolean
}

export function isDeniedInlineToolError(error: string | undefined): boolean {
  if (!error) return false
  return DENIED_ERROR_MARKERS.some((marker) => error.includes(marker))
}

export function deriveInlineToolState(input: { error?: string; onClick?: boolean }): InlineToolState {
  const denied = isDeniedInlineToolError(input.error)
  const failed = Boolean(input.error && !denied)
  return {
    denied,
    failed,
    clickable: Boolean(input.onClick || failed),
  }
}
