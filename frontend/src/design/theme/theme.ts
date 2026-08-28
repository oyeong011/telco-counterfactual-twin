import { z } from "zod"

export const THEME_STORAGE_KEY = "twin-theme"
export const SYSTEM_THEME_QUERY = "(prefers-color-scheme: dark)"

export const ThemePreferenceSchema = z.enum(["light", "dark", "system"])

export type ThemePreference = z.infer<typeof ThemePreferenceSchema>
export type ResolvedTheme = Exclude<ThemePreference, "system">

function assertNever(value: never): never {
  throw new TypeError(`Unsupported theme preference: ${String(value)}`)
}

export function parseThemePreference(value: string | null): ThemePreference {
  return ThemePreferenceSchema.catch("system").parse(value)
}

export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  switch (preference) {
    case "light":
      return "light"
    case "dark":
      return "dark"
    case "system":
      return systemPrefersDark ? "dark" : "light"
    default:
      return assertNever(preference)
  }
}
