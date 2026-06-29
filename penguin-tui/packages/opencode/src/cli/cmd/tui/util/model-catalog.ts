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

export type ModelCatalogModel = Omit<CatalogModelInput, "capabilities" | "id" | "providerID"> & {
  id: string
  providerID: string
  capabilities: {
    attachment: boolean
    reasoning: boolean
    temperature: boolean
    toolcall: boolean
  }
}

export type ModelCatalogProvider = {
  id: string
  name: string
  env: string[]
  models: Record<string, ModelCatalogModel>
}

const SPARSE_MODEL_CATALOG_LIMIT = 20

function normalizeModel(providerID: string, modelID: string, model: CatalogModelInput): ModelCatalogModel {
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

function normalizeModels(provider: CatalogProviderInput): Record<string, ModelCatalogModel> {
  return Object.fromEntries(
    Object.entries(provider.models ?? {}).map(([modelID, model]) => [
      modelID,
      normalizeModel(provider.id, modelID, model),
    ]),
  )
}

export function modelCatalogCount(providers: ReadonlyArray<{ models?: Record<string, unknown> | null }>): number {
  return providers.reduce((total, provider) => total + Object.keys(provider.models ?? {}).length, 0)
}

export function hasSparseModelCatalog(providers: ReadonlyArray<{ models?: Record<string, unknown> | null }>): boolean {
  const modelCount = modelCatalogCount(providers)
  return modelCount > 0 && modelCount < SPARSE_MODEL_CATALOG_LIMIT
}

/**
 * Build the catalog used by model-selection UI and validation.
 *
 * Penguin's `/config/providers` payload can be sparse during cold startup
 * because it starts from configured aliases. `/provider` carries the broader
 * available-provider catalog once backend discovery has warmed. Merge both so
 * configured aliases keep their richer runtime payloads while the picker can
 * show the discovered catalog.
 */
export function createModelCatalogProviders(
  configuredProviders: CatalogProviderInput[],
  availableProviders: CatalogProviderInput[],
): ModelCatalogProvider[] {
  const orderedIDs = new Set<string>()
  for (const provider of configuredProviders) orderedIDs.add(provider.id)
  for (const provider of availableProviders) orderedIDs.add(provider.id)

  const merged: ModelCatalogProvider[] = []
  for (const providerID of orderedIDs) {
    const configured = configuredProviders.find((provider) => provider.id === providerID)
    const available = availableProviders.find((provider) => provider.id === providerID)
    if (!configured && !available) continue

    merged.push({
      id: providerID,
      name: configured?.name ?? available?.name ?? providerID,
      env: configured?.env ?? available?.env ?? [],
      models: {
        ...(available ? normalizeModels(available) : {}),
        ...(configured ? normalizeModels(configured) : {}),
      },
    })
  }

  return merged
}
