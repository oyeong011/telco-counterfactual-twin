export const SAFE_KEY_PATTERN =
  /^(?!(?:email|gpsi|imei|imsi|msisdn|phone|subscriber[-_]?id|supi|apply[-_]?to[-_]?network|command|execute|execution|push[-_]?config|revoke|revocation|shell|url)$)[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$/

const SAFE_EXACT_KEYS = new Set(
  [
    "commandment_count",
    "config_history",
    "curiosity_score",
    "duration_ms",
    "executioner_state",
    "flourish_count",
    "jurisdiction_code",
    "maturity_score",
    "purity_index",
    "security_level",
    "shellfish_count",
    "tokenization_mode",
    "ue_cohort_id",
  ].map((key) => key.replace(/[^a-z0-9]/g, "")),
)

function normalizedKeyTokens(value: string): readonly string[] {
  return value
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2")
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .split(/[^A-Za-z0-9]+/)
    .filter((token) => token.length > 0)
    .map((token) => token.toLowerCase())
}

function collapsedMatchesGroup(
  value: string,
  left: readonly string[],
  right: readonly string[],
): boolean {
  const familiesPresent =
    left.some((lexeme) => value.includes(lexeme)) && right.some((lexeme) => value.includes(lexeme))
  const adjacentPair = left.some((first) =>
    right.some((second) => value.includes(first + second) || value.includes(second + first)),
  )
  return familiesPresent || adjacentPair
}

function matchesApiGroup(parts: readonly string[], normalized: string): boolean {
  const tokenMatch =
    parts.includes("api") && ["key", "secret", "token"].some((target) => parts.includes(target))
  const shielded = normalized.replaceAll("rapid", "")
  const collapsedMatch =
    shielded.includes("api") &&
    ["key", "secret", "token"].some((target) => shielded.includes(target))
  return tokenMatch || collapsedMatch
}

export function semanticallySafeKey(value: string): boolean {
  const normalized = value.toLowerCase().replace(/[^a-z0-9]/g, "")
  if (SAFE_EXACT_KEYS.has(normalized)) return true
  const parts = normalizedKeyTokens(value)
  const has = (values: readonly string[]) => parts.some((part) => values.includes(part))
  const directPii = [
    "customer",
    "email",
    "gpsi",
    "imei",
    "imsi",
    "msisdn",
    "phone",
    "subscriber",
    "supi",
  ].some((stem) => normalized.includes(stem))
  const directAuthority = [
    "command",
    "execute",
    "execution",
    "revoke",
    "revocation",
    "shell",
    "url",
    "uri",
  ].some((stem) => normalized.includes(stem))
  const directSecret = ["credential", "passwd", "password", "secret", "token"].some((stem) =>
    normalized.includes(stem),
  )
  const apiSecret = matchesApiGroup(parts, normalized)
  const pii =
    (has(["customer", "subscriber"]) && has(["id", "identifier", "identifiers", "identity"])) ||
    collapsedMatchesGroup(
      normalized,
      ["customer", "subscriber"],
      ["id", "identifier", "identifiers", "identity"],
    )
  const authority =
    (has(["push"]) && has(["config", "network", "payload"])) ||
    collapsedMatchesGroup(normalized, ["push"], ["config", "network", "payload"]) ||
    (has(["apply"]) && has(["config", "network", "payload"])) ||
    collapsedMatchesGroup(normalized, ["apply"], ["config", "network", "payload"]) ||
    (has(["shell"]) && has(["command"])) ||
    collapsedMatchesGroup(normalized, ["shell"], ["command"]) ||
    (has(["arbitrary"]) && has(["uri", "url"])) ||
    collapsedMatchesGroup(normalized, ["arbitrary"], ["uri", "url"]) ||
    (has(["execute", "execution"]) &&
      has(["action", "command", "network", "operation", "payload", "plan", "request"])) ||
    collapsedMatchesGroup(
      normalized,
      ["execute", "execution"],
      ["action", "command", "network", "operation", "payload", "plan", "request"],
    ) ||
    (has(["command"]) && has(["action", "network", "operation", "payload", "plan", "request"])) ||
    collapsedMatchesGroup(
      normalized,
      ["command"],
      ["action", "network", "operation", "payload", "plan", "request"],
    ) ||
    (has(["revoke", "revocation"]) && has(["id", "identifier", "reason", "status", "token"])) ||
    collapsedMatchesGroup(
      normalized,
      ["revoke", "revocation"],
      ["id", "identifier", "reason", "status", "token"],
    )
  const secret = has(["credential", "passwd", "password", "secret", "token"])
  const accessSecret =
    (has(["access"]) && has(["key", "secret", "token"])) ||
    collapsedMatchesGroup(normalized, ["access"], ["key", "secret", "token"])
  return !(
    directPii ||
    directAuthority ||
    directSecret ||
    apiSecret ||
    pii ||
    authority ||
    secret ||
    accessSecret
  )
}
