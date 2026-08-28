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

export type SessionStorageLike = {
  readonly getItem: (key: string) => string | null
  readonly setItem: (key: string, value: string) => void
  readonly removeItem: (key: string) => void
}

export type RunDraftIndex = {
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
    runId: ContractIdSchema,
    scenarioId: ContractIdSchema,
    patchId: ContractIdSchema.optional(),
    patchBody: TypedPatchSchema.optional(),
    simulationId: ContractIdSchema.optional(),
    comparisonId: ContractIdSchema.optional(),
    approvalRequestId: ContractIdSchema.optional(),
  })
  .strict()
const runDraftsSchema = z.array(RunDraftIndexSchema).max(128)

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

function readStoredDrafts(storage: SessionStorageLike): readonly RunDraftIndex[] {
  const serialized = storage.getItem(RUN_DRAFTS_STORAGE_KEY)
  if (serialized === null) return []
  let raw: unknown
  try {
    raw = JSON.parse(serialized)
  } catch (error) {
    if (error instanceof SyntaxError)
      throw new StorageContractError("stored run drafts are not valid JSON", { cause: error })
    throw error
  }
  const parsed = runDraftsSchema.safeParse(raw)
  if (!parsed.success)
    throw new StorageContractError("stored run drafts violate the public contract", {
      cause: parsed.error,
    })
  return parsed.data
}

export class SessionStorageAdapter {
  readonly storage: SessionStorageLike

  constructor(storage: SessionStorageLike = defaultStorage()) {
    this.storage = storage
  }

  listRunDrafts(): readonly RunDraftIndex[] {
    return readStoredDrafts(this.storage)
  }

  getRunDraft(runId: ContractId): RunDraftIndex | null {
    return this.listRunDrafts().find((draft) => draft.runId === runId) ?? null
  }

  saveRunDraft(draft: RunDraftIndex): void {
    const parsed = RunDraftIndexSchema.parse(draft)
    const next = [...this.listRunDrafts().filter((item) => item.runId !== parsed.runId), parsed]
    this.storage.setItem(RUN_DRAFTS_STORAGE_KEY, JSON.stringify(runDraftsSchema.parse(next)))
  }

  removeRunDraft(runId: ContractId): void {
    const next = this.listRunDrafts().filter((draft) => draft.runId !== runId)
    if (next.length === 0) {
      this.storage.removeItem(RUN_DRAFTS_STORAGE_KEY)
      return
    }
    this.storage.setItem(RUN_DRAFTS_STORAGE_KEY, JSON.stringify(runDraftsSchema.parse(next)))
  }
}

export function createSessionStorageAdapter(storage?: SessionStorageLike): SessionStorageAdapter {
  return new SessionStorageAdapter(storage)
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
