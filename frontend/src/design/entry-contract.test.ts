import { describe, expect, it } from "vitest"
import indexHtml from "../../index.html?raw"
import mainSource from "../main.tsx?raw"

describe("document entry contract", () => {
  it("declares an embedded favicon so production navigation has no icon request failure", () => {
    // Given
    const faviconPattern = /<link\s+rel="icon"\s+href="data:,"\s*\/>/

    // When
    const hasEmbeddedFavicon = faviconPattern.test(indexHtml)

    // Then
    expect(hasEmbeddedFavicon).toBe(true)
  })

  it("keeps the development-only preview stylesheet out of the production entry graph", () => {
    // Given
    const developmentOnlyStylesheetImport = /import ["']\.\/styles\/showcase\.css["']/

    // When
    const productionEntryImportsPreviewStyles = developmentOnlyStylesheetImport.test(mainSource)

    // Then
    expect(productionEntryImportsPreviewStyles).toBe(false)
  })

  it("allows disabling both React development overlays with the Vite flag", () => {
    // Given
    const devToolsGate =
      /import\.meta\.env\.DEV\s*&&\s*import\.meta\.env\.VITE_DISABLE_REACT_DEVTOOLS\s*!==\s*["']1["']/s

    // When
    const hasFlaggedDevToolsGate = devToolsGate.test(mainSource)

    // Then
    expect(hasFlaggedDevToolsGate).toBe(true)
  })
})
