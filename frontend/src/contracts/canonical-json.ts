export class CanonicalJsonError extends Error {
  override readonly name = "CanonicalJsonError"
}

export function canonicalJson(value: unknown): string {
  if (value === null) return "null"
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`
  if (typeof value === "object") {
    const entries = Object.entries(value).sort(([left], [right]) => {
      if (left < right) return -1
      if (left > right) return 1
      return 0
    })
    return `{${entries
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
      .join(",")}}`
  }
  const serialized = JSON.stringify(value)
  if (serialized === undefined) throw new CanonicalJsonError("value is outside the JSON domain")
  return serialized
}
