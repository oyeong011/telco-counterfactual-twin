import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from "react"
import {
  parseThemePreference,
  type ResolvedTheme,
  resolveTheme,
  SYSTEM_THEME_QUERY,
  THEME_STORAGE_KEY,
  type ThemePreference,
} from "./theme"

type ThemeContextValue = {
  readonly preference: ThemePreference
  readonly resolvedTheme: ResolvedTheme
  readonly setPreference: (preference: ThemePreference) => void
}

type ThemeProviderProps = {
  readonly children: ReactNode
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function getInitialPreference(): ThemePreference {
  return parseThemePreference(window.localStorage.getItem(THEME_STORAGE_KEY))
}

function getSystemPreference(): boolean {
  return window.matchMedia(SYSTEM_THEME_QUERY).matches
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  const [preference, setPreferenceState] = useState<ThemePreference>(getInitialPreference)
  const [systemPrefersDark, setSystemPrefersDark] = useState(getSystemPreference)
  const resolvedTheme = resolveTheme(preference, systemPrefersDark)

  useEffect(() => {
    const mediaQuery = window.matchMedia(SYSTEM_THEME_QUERY)
    const handleChange = (event: MediaQueryListEvent) => setSystemPrefersDark(event.matches)
    mediaQuery.addEventListener("change", handleChange)
    return () => mediaQuery.removeEventListener("change", handleChange)
  }, [])

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", resolvedTheme)
    window.localStorage.setItem(THEME_STORAGE_KEY, preference)
  }, [preference, resolvedTheme])

  const value = useMemo<ThemeContextValue>(
    () => ({
      preference,
      resolvedTheme,
      setPreference: setPreferenceState,
    }),
    [preference, resolvedTheme],
  )

  return <ThemeContext value={value}>{children}</ThemeContext>
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext)
  if (context === null) {
    throw new TypeError("useTheme must be used within ThemeProvider")
  }
  return context
}
