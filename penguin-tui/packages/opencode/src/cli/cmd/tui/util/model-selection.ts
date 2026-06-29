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

export function resolveCatalogModel(providers: CatalogProvider[], model: ModelSelection): ModelSelection | undefined {
  const provider = providers.find((item) => sameModelID(item.id, model.providerID))
  if (!provider?.models) return undefined

  const directCatalogID = Object.keys(provider.models).find((catalogID) => sameModelID(catalogID, model.modelID))
  if (directCatalogID) {
    return {
      providerID: provider.id,
      modelID: directCatalogID,
    }
  }

  for (const [catalogID, info] of Object.entries(provider.models)) {
    if (
      sameModelID(catalogID, model.modelID) ||
      sameModelID(info.id, model.modelID) ||
      sameModelID(info.name, model.modelID)
    ) {
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
