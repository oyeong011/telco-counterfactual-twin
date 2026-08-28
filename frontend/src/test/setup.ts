import "@testing-library/jest-dom/vitest"
import { cleanup } from "@testing-library/react"
import { afterEach } from "vitest"

const storedValues = new Map<string, string>()
const localStorageStub = {
  get length() {
    return storedValues.size
  },
  clear() {
    storedValues.clear()
  },
  getItem(key: string) {
    return storedValues.get(key) ?? null
  },
  key(index: number) {
    return Array.from(storedValues.keys()).at(index) ?? null
  },
  removeItem(key: string) {
    storedValues.delete(key)
  },
  setItem(key: string, value: string) {
    storedValues.set(key, value)
  },
} satisfies Storage

Object.defineProperty(window, "localStorage", {
  configurable: true,
  value: localStorageStub,
})

afterEach(() => cleanup())
