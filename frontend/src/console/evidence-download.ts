import type { EvidenceResponse } from "../contracts/generated"

export type EvidenceDownloadPort = {
  readonly document: Document
  readonly createObjectUrl: (blob: Blob) => string
  readonly revokeObjectUrl: (url: string) => void
  readonly defer: (task: () => void) => void
}

function evidenceBlob(evidence: EvidenceResponse): Blob {
  return new Blob([JSON.stringify(evidence, null, 2)], { type: "application/json" })
}

function clickDownload(evidence: EvidenceResponse, url: string, owner: Document): void {
  const link = owner.createElement("a")
  link.href = url
  link.download = `${evidence.evidence_card.evidence_id}.json`
  link.hidden = true
  owner.body.append(link)
  link.click()
  link.remove()
}

function downloadWithPort(evidence: EvidenceResponse, port: EvidenceDownloadPort): void {
  const url = port.createObjectUrl(evidenceBlob(evidence))
  clickDownload(evidence, url, port.document)
  port.defer(() => port.revokeObjectUrl(url))
}

export function downloadEvidenceJson(evidence: EvidenceResponse): void {
  const url = URL.createObjectURL(evidenceBlob(evidence))
  clickDownload(evidence, url, document)
  queueMicrotask(() => URL.revokeObjectURL(url))
}

export function downloadEvidenceJsonWithPort(
  evidence: EvidenceResponse,
  port: EvidenceDownloadPort,
): void {
  downloadWithPort(evidence, port)
}
