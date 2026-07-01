import path from "path"
import { pathToFileURL } from "url"

export type FileAutocompleteLineRange = {
  startLine: number
  endLine?: number
}

export function fileAutocompleteURL(input: {
  baseDirectory: string
  item: string
  lineRange?: FileAutocompleteLineRange
}): string {
  const filePath = path.isAbsolute(input.item) ? input.item : path.join(input.baseDirectory, input.item)
  const url = pathToFileURL(filePath)
  if (input.lineRange) {
    url.searchParams.set("start", String(input.lineRange.startLine))
    if (input.lineRange.endLine !== undefined) {
      url.searchParams.set("end", String(input.lineRange.endLine))
    }
  }
  return url.toString()
}
