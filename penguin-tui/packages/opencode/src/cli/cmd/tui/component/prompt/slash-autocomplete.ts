export type SlashAutocompleteOption = {
  display: string
  value?: string
  aliases?: string[]
}

function normalizeText(input: string) {
  const text = input.trim().toLowerCase()
  return text.startsWith("/") ? text.slice(1) : text
}

function normalizeName(input: string) {
  const text = normalizeText(input)
  const [name] = text.split(/\s+/)
  return name?.replace(/:(mcp|skill)$/, "") ?? ""
}

function normalizeAlias(input: string) {
  return normalizeText(input)
}

function optionNames(option: SlashAutocompleteOption) {
  return [normalizeName(option.value ?? option.display), ...(option.aliases ?? []).map(normalizeAlias)].filter(Boolean)
}

function rankName(query: string, name: string) {
  if (name === query) return 0
  if (query === "mo" && name === "models") return 1
  if (name.startsWith(query)) return 2
  if (name.includes(query)) return 3
  return 4
}

export function rankSlashAutocompleteOptions<T extends SlashAutocompleteOption>(query: string, options: T[]): T[] {
  const text = normalizeText(query)
  if (!text) return options

  return options
    .map((option, index) => ({
      option,
      index,
      rank: Math.min(...optionNames(option).map((name) => rankName(text, name))),
    }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map((item) => item.option)
}
