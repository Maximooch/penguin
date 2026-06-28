export type ModelSelection = {
  providerID: string
  modelID: string
}

type CatalogModel = {
  id?: string
  name?: string
}

type CatalogProvider = {
  id: string
  models?: Record<string, CatalogModel>
}

function sameModelID(left: string | undefined, right: string): boolean {
  return typeof left === "string" && left.toLowerCase() === right.toLowerCase()
}

export function resolveCatalogModel(
  providers: CatalogProvider[],
  model: ModelSelection,
): ModelSelection | undefined {
  const provider = providers.find((item) => item.id === model.providerID)
  if (!provider?.models) return undefined

  if (provider.models[model.modelID]) {
    return {
      providerID: provider.id,
      modelID: model.modelID,
    }
  }

  for (const [catalogID, info] of Object.entries(provider.models)) {
    if (sameModelID(info.id, model.modelID) || sameModelID(info.name, model.modelID)) {
      return {
        providerID: provider.id,
        modelID: catalogID,
      }
    }
  }

  return undefined
}

export function isCatalogModelValid(providers: CatalogProvider[], model: ModelSelection): boolean {
  return resolveCatalogModel(providers, model) !== undefined
}
