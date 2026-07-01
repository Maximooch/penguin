export type VariantCycleResult =
  | {
      type: "unavailable"
    }
  | {
      type: "selected"
      variant: string | undefined
    }

export function nextVariantSelection(variants: string[], current: string | undefined): VariantCycleResult {
  if (variants.length === 0) {
    return { type: "unavailable" }
  }

  if (!current) {
    return { type: "selected", variant: variants[0] }
  }

  const index = variants.indexOf(current)
  if (index === -1 || index === variants.length - 1) {
    return { type: "selected", variant: undefined }
  }

  return { type: "selected", variant: variants[index + 1] }
}
