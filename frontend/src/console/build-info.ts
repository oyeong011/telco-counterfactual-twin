import ky from "ky"
import { type UiBuildInfo, UiBuildInfoSchema } from "../contracts/generated"

export type BuildInfoState =
  | { readonly kind: "available"; readonly value: UiBuildInfo }
  | { readonly kind: "unavailable"; readonly detail: string }

export async function loadUiBuildInfo(): Promise<BuildInfoState> {
  try {
    const response = await ky.get("/build-info.json", { throwHttpErrors: false, retry: 0 })
    if (!response.ok)
      return {
        kind: "unavailable",
        detail: `Static build identity returned ${response.status}.`,
      }
    const parsed = UiBuildInfoSchema.safeParse(await response.json())
    return parsed.success
      ? { kind: "available", value: parsed.data }
      : { kind: "unavailable", detail: "Static build identity failed schema validation." }
  } catch (error) {
    if (error instanceof Error)
      return {
        kind: "unavailable",
        detail: "Static build identity could not be fetched.",
      }
    throw error
  }
}
