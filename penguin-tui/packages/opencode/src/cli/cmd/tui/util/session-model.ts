export type SessionModelSelection = {
  providerID?: string
  modelID?: string
  variant?: string
  source?: string
  sessionScoped?: boolean
}

export type SessionModelHydration = {
  providerID?: string
  modelID?: string
  variant?: string
  modelSelection?: SessionModelSelection
}

function hasModel(value: { providerID?: string; modelID?: string } | undefined) {
  return (
    typeof value?.providerID === "string" && !!value.providerID && typeof value?.modelID === "string" && !!value.modelID
  )
}

export function hydratedSessionModel(session: SessionModelHydration | undefined) {
  if (!session) return undefined
  const selection = session.modelSelection
  if (selection) {
    if (!selection.sessionScoped) return undefined
    if (!hasModel(selection)) return undefined
    return {
      providerID: selection.providerID!,
      modelID: selection.modelID!,
    }
  }

  if (!hasModel(session)) return undefined
  return {
    providerID: session.providerID!,
    modelID: session.modelID!,
  }
}

export function hydratedSessionVariant(session: SessionModelHydration | undefined) {
  const selection = session?.modelSelection
  if (selection) return selection.sessionScoped && typeof selection.variant === "string" ? selection.variant : undefined
  return typeof session?.variant === "string" ? session.variant : undefined
}
