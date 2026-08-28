export function resolveApiBaseUrl(explicit: string | undefined): string {
  // biome-ignore lint/complexity/useLiteralKeys: Vite exposes env values through an index signature.
  const configured = explicit ?? import.meta.env["VITE_API_BASE_URL"]
  if (configured && configured.trim().length > 0) return configured.replace(/\/$/, "")
  if (typeof window !== "undefined" && window.location.origin.length > 0) {
    return window.location.origin
  }
  return ""
}

export function apiPath(baseUrl: string, path: string): string {
  const normalizedPath = path.replace(/^\/+/, "")
  return `${baseUrl.replace(/\/$/, "")}/${normalizedPath}`
}
