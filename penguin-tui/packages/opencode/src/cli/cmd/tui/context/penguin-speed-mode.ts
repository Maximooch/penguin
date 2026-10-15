// Preserve legacy boolean fast preferences while adding one exclusive ultrafast value.
export type PenguinSpeedPreference = boolean | "ultrafast" | undefined

export function isPenguinSpeedPreference(value: unknown): value is boolean | "ultrafast" {
  return typeof value === "boolean" || value === "ultrafast"
}

export function createPenguinSpeedModes(input: {
  get(): PenguinSpeedPreference
  set(value: PenguinSpeedPreference): void
  configured(): string | undefined
}) {
  const enabled = (value: true | "ultrafast", tier: string) =>
    input.get() === undefined ? input.configured()?.trim().toLowerCase() === tier : input.get() === value
  return {
    ultrafast: {
      enabled: () => enabled("ultrafast", "ultrafast"),
      set(value: boolean | undefined) {
        input.set(value === undefined ? undefined : value ? "ultrafast" : false)
      },
      toggle() {
        this.set(!this.enabled())
      },
    },
    fast: {
      override: input.get,
      enabled: () => enabled(true, "priority"),
      set: input.set,
      toggle() {
        this.set(!this.enabled())
      },
      serviceTier() {
        const value = input.get()
        if (value === undefined) return undefined
        if (value === "ultrafast") return "ultrafast"
        return value ? "priority" : "default"
      },
    },
  }
}
