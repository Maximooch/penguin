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
  catalog?: {
    model_count?: number
    sparse?: boolean
    state?: string
  }
  connected?: boolean
  id: string
  name?: string
  env?: string[]
  models?: Record<string, CatalogModelInput>
  source?: string
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

type CatalogState = NonNullable<CatalogProviderInput["catalog"]>

export type ModelCatalogProvider = {
  catalog?: {
    model_count?: number
    sparse?: boolean
    state?: string
  }
  connected?: boolean
  id: string
  name: string
  env: string[]
  models: Record<string, ModelCatalogModel>
  source?: string
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

function mergeCapabilities(
  available?: ModelCatalogModel["capabilities"],
  configured?: ModelCatalogModel["capabilities"],
): ModelCatalogModel["capabilities"] {
  return {
    attachment: Boolean(available?.attachment || configured?.attachment),
    reasoning: Boolean(available?.reasoning || configured?.reasoning),
    temperature: Boolean(available?.temperature || configured?.temperature),
    toolcall: Boolean(available?.toolcall || configured?.toolcall),
  }
}

function mergeRecords<T>(
  available: Record<string, T> | undefined,
  configured: Record<string, T> | undefined,
): Record<string, T> | undefined {
  const merged = {
    ...(available ?? {}),
    ...(configured ?? {}),
  }
  return Object.keys(merged).length > 0 ? merged : undefined
}

function catalogModelCount(catalog: CatalogState | undefined): number {
  const count = catalog?.model_count
  return typeof count === "number" && count >= 0 ? count : 0
}

function mergeCatalogState(
  configured: CatalogState | undefined,
  available: CatalogState | undefined,
): CatalogState | undefined {
  if (!configured) return available
  if (!available) return configured
  if (configured.sparse === true && available.sparse === false) return available
  if (catalogModelCount(available) > catalogModelCount(configured)) return available
  return configured
}

function mergeModelMaps(
  availableModels: Record<string, ModelCatalogModel>,
  configuredModels: Record<string, ModelCatalogModel>,
): Record<string, ModelCatalogModel> {
  const merged = { ...availableModels }

  for (const [modelID, configured] of Object.entries(configuredModels)) {
    const available = merged[modelID]
    if (!available) {
      merged[modelID] = configured
      continue
    }

    const model = {
      ...available,
      ...configured,
      capabilities: mergeCapabilities(available.capabilities, configured.capabilities),
    }
    const variants = mergeRecords(available.variants, configured.variants)
    if (variants) model.variants = variants
    const options = mergeRecords(available.options, configured.options)
    if (options) model.options = options
    const cost = mergeRecords(available.cost, configured.cost)
    if (cost) model.cost = cost
    merged[modelID] = model
  }

  return merged
}

export function modelCatalogCount(providers: ReadonlyArray<{ models?: Record<string, unknown> | null }>): number {
  return providers.reduce((total, provider) => total + Object.keys(provider.models ?? {}).length, 0)
}

export function hasSparseModelCatalog(
  providers: ReadonlyArray<{
    catalog?: { sparse?: boolean; state?: string } | null
    models?: Record<string, unknown> | null
  }>,
): boolean {
  const heuristicProviders = []
  for (const provider of providers) {
    if (provider.catalog?.sparse === true) return true
    if (provider.catalog?.state === "sparse") return true
    if (provider.catalog) continue
    heuristicProviders.push(provider)
  }

  const modelCount = modelCatalogCount(heuristicProviders)
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
      catalog: mergeCatalogState(configured?.catalog, available?.catalog),
      connected: configured?.connected ?? available?.connected,
      id: providerID,
      name: configured?.name ?? available?.name ?? providerID,
      env: configured?.env ?? available?.env ?? [],
      models: mergeModelMaps(
        available ? normalizeModels(available) : {},
        configured ? normalizeModels(configured) : {},
      ),
      source: configured?.source ?? available?.source,
    })
  }

  return merged
}
