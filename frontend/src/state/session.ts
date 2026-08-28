import { z } from "zod"
import { type SessionAuth, sessionAuthFromResponse } from "../api/auth"
import {
  type ContractId,
  ContractIdSchema,
  type DemoSessionResponse,
  type TypedPatch,
  TypedPatchSchema,
} from "../contracts/generated"

export const RUN_DRAFTS_STORAGE_KEY = "telco-twin:run-drafts"
const scopedDraftsKey = (sessionId: ContractId): string => `${RUN_DRAFTS_STORAGE_KEY}:${sessionId}`

export type SessionStorageLike = {
  readonly getItem: (key: string) => string | null
  readonly setItem: (key: string, value: string) => void
  readonly removeItem: (key: string) => void
}

export type RunDraftIndex = {
  readonly sessionId: ContractId
  readonly runId: ContractId
  readonly scenarioId: ContractId
  readonly patchId?: ContractId | undefined
  readonly patchBody?: TypedPatch | undefined
  readonly simulationId?: ContractId | undefined
  readonly comparisonId?: ContractId | undefined
  readonly approvalRequestId?: ContractId | undefined
}

export const RunDraftIndexSchema = z
  .object({
    sessionId: ContractIdSchema,
    runId: ContractIdSchema,
    scenarioId: ContractIdSchema,
    patchId: ContractIdSchema.optional(),
    patchBody: TypedPatchSchema.optional(),
    simulationId: ContractIdSchema.optional(),
    comparisonId: ContractIdSchema.optional(),
    approvalRequestId: ContractIdSchema.optional(),
  })
  .strict()
const runDraftsSchema = z
  .array(RunDraftIndexSchema)
  .max(128)
  .superRefine((drafts, context) => {
    const runIds = new Set<string>()
    for (const [index, draft] of drafts.entries()) {
      if (runIds.has(draft.runId)) {
        context.addIssue({
          code: "custom",
          path: [index, "runId"],
          message: "run draft IDs must be unique within one session",
        })
      }
      runIds.add(draft.runId)
    }
  })

export class StorageContractError extends Error {
  override readonly name = "StorageContractError"
}

class MemoryStorage implements SessionStorageLike {
  private readonly values = new Map<string, string>()

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value)
  }

  removeItem(key: string): void {
    this.values.delete(key)
  }
}

function defaultStorage(): SessionStorageLike {
  if (typeof globalThis.sessionStorage !== "undefined") return globalThis.sessionStorage
  return new MemoryStorage()
}

function decodeDrafts(serialized: string): readonly RunDraftIndex[] | null {
  let raw: unknown
  try {
    raw = JSON.parse(serialized)
  } catch (error) {
    if (error instanceof SyntaxError) return null
    throw error
  }
  const parsed = runDraftsSchema.safeParse(raw)
  return parsed.success ? parsed.data : null
}

function readStoredDrafts(
  storage: SessionStorageLike,
  key: string,
): readonly RunDraftIndex[] | null {
  const serialized = storage.getItem(key)
  if (serialized === null) return []
  return decodeDrafts(serialized)
}

function discardLegacyDrafts(storage: SessionStorageLike): boolean {
  const serialized = storage.getItem(RUN_DRAFTS_STORAGE_KEY)
  if (serialized === null) return false
  storage.removeItem(RUN_DRAFTS_STORAGE_KEY)
  return true
}

export class SessionStorageAdapter {
  readonly storage: SessionStorageLike
  readonly sessionId: ContractId | undefined
  private lastCorruption: StorageContractError | null = null

  constructor(storage: SessionStorageLike = defaultStorage(), sessionId?: ContractId) {
    this.storage = storage
    this.sessionId = sessionId
  }

  listRunDrafts(sessionId = this.sessionId): readonly RunDraftIndex[] {
    const discardedLegacy = discardLegacyDrafts(this.storage)
    if (this.sessionId !== undefined && sessionId !== undefined && this.sessionId !== sessionId)
      return []
    if (sessionId === undefined) {
      if (discardedLegacy)
        this.lastCorruption = new StorageContractError("legacy run drafts were discarded")
      return []
    }
    const key = scopedDraftsKey(sessionId)
    const drafts = readStoredDrafts(this.storage, key)
    if (drafts?.every((draft) => draft.sessionId === sessionId)) return drafts
    this.lastCorruption = new StorageContractError(
      "stored run drafts were discarded after contract failure",
    )
    this.storage.removeItem(key)
    return []
  }

  getRunDraft(runId: ContractId, sessionId = this.sessionId): RunDraftIndex | null {
    return this.listRunDrafts(sessionId).find((draft) => draft.runId === runId) ?? null
  }

  saveRunDraft(draft: RunDraftIndex): void {
    const parsed = RunDraftIndexSchema.parse(draft)
    if (this.sessionId !== undefined && this.sessionId !== parsed.sessionId)
      throw new StorageContractError("run draft session binding does not match adapter scope")
    const next = [
      ...this.listRunDrafts(parsed.sessionId).filter((item) => item.runId !== parsed.runId),
      parsed,
    ]
    this.storage.setItem(
      scopedDraftsKey(parsed.sessionId),
      JSON.stringify(runDraftsSchema.parse(next)),
    )
  }

  removeRunDraft(runId: ContractId, sessionId = this.sessionId): void {
    if (sessionId === undefined) return
    if (this.sessionId !== undefined && this.sessionId !== sessionId) return
    const key = scopedDraftsKey(sessionId)
    const next = this.listRunDrafts(sessionId).filter((draft) => draft.runId !== runId)
    if (next.length === 0) {
      this.storage.removeItem(key)
      return
    }
    this.storage.setItem(key, JSON.stringify(runDraftsSchema.parse(next)))
  }

  resetRunDrafts(sessionId = this.sessionId): void {
    this.storage.removeItem(RUN_DRAFTS_STORAGE_KEY)
    if (sessionId !== undefined) this.storage.removeItem(scopedDraftsKey(sessionId))
    this.lastCorruption = null
  }

  takeLastCorruption(): StorageContractError | null {
    const corruption = this.lastCorruption
    this.lastCorruption = null
    return corruption
  }

  forSession(sessionId: ContractId): SessionStorageAdapter {
    return new SessionStorageAdapter(this.storage, sessionId)
  }
}

export function createSessionStorageAdapter(
  storage?: SessionStorageLike,
  sessionId?: ContractId,
): SessionStorageAdapter {
  return new SessionStorageAdapter(storage, sessionId)
}

export class InMemorySessionStore {
  private current: DemoSessionResponse | null = null

  set(session: DemoSessionResponse): void {
    this.current = session
  }

  get(): DemoSessionResponse | null {
    return this.current
  }

  getAuth(): SessionAuth | null {
    return this.current === null ? null : sessionAuthFromResponse(this.current)
  }

  clear(): void {
    this.current = null
  }
}

export function createSessionStore(): InMemorySessionStore {
  return new InMemorySessionStore()
}
