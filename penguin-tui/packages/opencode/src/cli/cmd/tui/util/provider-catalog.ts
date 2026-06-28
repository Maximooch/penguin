type CatalogModelInput = {
  id?: string
  name?: string
  providerID?: string
  release_date?: string
  status?: string
  cost?: {
    input?: number
  }
  variants?: Record<string, unknown>
  capabilities?: {
    attachment?: boolean
    reasoning?: boolean
    temperature?: boolean
    toolcall?: boolean
  }
  attachment?: boolean
  reasoning?: boolean
  temperature?: boolean
  tool_call?: boolean
  limit?: unknown
  options?: Record<string, unknown>
}

type CatalogProviderInput = {
  id: string
  name?: string
  env?: string[]
  models?: Record<string, CatalogModelInput>
}

export type CatalogModel = Omit<CatalogModelInput, "capabilities" | "id" | "providerID"> & {
  id: string
  providerID: string
  capabilities: {
    attachment: boolean
    reasoning: boolean
    temperature: boolean
    toolcall: boolean
  }
}

export type CatalogProvider = {
  id: string
  name: string
  env: string[]
  models: Record<string, CatalogModel>
}

function normalizeModel(providerID: string, modelID: string, model: CatalogModelInput): CatalogModel {
  const capabilities = {
    ...model.capabilities,
    attachment: model.capabilities?.attachment ?? model.attachment ?? false,
    reasoning: model.capabilities?.reasoning ?? model.reasoning ?? false,
    temperature: model.capabilities?.temperature ?? model.temperature ?? false,
    toolcall: model.capabilities?.toolcall ?? model.tool_call ?? false,
  }

  return {
    ...model,
    id: model.id ?? modelID,
    providerID: model.providerID ?? providerID,
    capabilities,
  }
}

function normalizeModels(provider: CatalogProviderInput): Record<string, CatalogModel> {
  return Object.fromEntries(
    Object.entries(provider.models ?? {}).map(([modelID, model]) => [
      modelID,
      normalizeModel(provider.id, modelID, model),
    ]),
  )
}

/**
 * Merge Penguin's configured provider catalog with the OpenCode-compatible
 * provider list. `/config/providers` can be sparse, while `/provider` carries
 * the broader picker catalog.
 */
export function mergeProviderCatalogs(
  configuredProviders: CatalogProviderInput[],
  providerListProviders: CatalogProviderInput[],
): CatalogProvider[] {
  const orderedIDs = new Set<string>()
  for (const provider of configuredProviders) orderedIDs.add(provider.id)
  for (const provider of providerListProviders) orderedIDs.add(provider.id)

  const merged: CatalogProvider[] = []
  for (const providerID of orderedIDs) {
    const configured = configuredProviders.find((provider) => provider.id === providerID)
    const listed = providerListProviders.find((provider) => provider.id === providerID)
    if (!configured && !listed) continue

    const listedModels = listed ? normalizeModels(listed) : {}
    const configuredModels = configured ? normalizeModels(configured) : {}
    merged.push({
      id: providerID,
      name: configured?.name ?? listed?.name ?? providerID,
      env: configured?.env ?? listed?.env ?? [],
      models: {
        ...listedModels,
        ...configuredModels,
      },
    })
  }

  return merged
}
