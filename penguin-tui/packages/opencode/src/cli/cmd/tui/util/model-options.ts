import { sortBy } from "remeda"

export function sortModelOptions<T extends { footer?: string; releaseDate?: string; title: string }>(
  options: T[],
  newestFirst: boolean,
): T[] {
  if (newestFirst) {
    return sortBy(options, [(option) => option.releaseDate ?? "", "desc"], (option) => option.title)
  }

  return sortBy(
    options,
    (option) => option.footer !== "Free",
    (option) => option.title,
  )
}
