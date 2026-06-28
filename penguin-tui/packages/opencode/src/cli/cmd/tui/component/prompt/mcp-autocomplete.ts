import { Locale } from "@/util/locale"

export type McpResourceAutocompleteSource = {
  name: string
  uri: string
}

export function formatMcpResourceAutocomplete(
  resource: McpResourceAutocompleteSource,
  width: number,
): {
  display: string
  value: string
} {
  return {
    display: Locale.truncateMiddle(resource.name, width),
    value: resource.name,
  }
}
