import AxeBuilder from "@axe-core/playwright"
import { expect, type Locator, type Page, test } from "@playwright/test"

function stateCard(page: Page, primitive: string, state = "default"): Locator {
  return page.locator(`[data-primitive="${primitive}"] article[data-showcase-state="${state}"]`)
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto("/__showcase")
  await expect(
    page.getByRole("heading", { name: "Evidence-first console primitives" }),
  ).toBeVisible()
})

test("contains all six mobile navigation items without horizontal scrolling", async ({ page }) => {
  // Given
  const navigation = page.getByRole("navigation", { name: "Primary" })

  // When
  const result = await navigation.evaluate((element) => {
    const bounds = element.getBoundingClientRect()
    const links = Array.from(element.querySelectorAll(".primaryNavLink"), (link) => {
      const item = link.getBoundingClientRect()
      return {
        label: link.textContent?.trim() ?? "",
        height: item.height,
        contained:
          item.left >= bounds.left &&
          item.right <= bounds.right &&
          item.top >= bounds.top &&
          item.bottom <= bounds.bottom,
      }
    })
    return {
      links,
      scrollFree: element.scrollWidth <= element.clientWidth,
    }
  })

  // Then
  expect(result.links).toHaveLength(6)
  expect(result.links.every((item) => item.contained)).toBe(true)
  expect(result.links.every((item) => item.height >= 44)).toBe(true)
  expect(result.scrollFree).toBe(true)
})

test("keeps topology label plates clear of node and edge bounds", async ({ page }) => {
  // Given
  const topology = stateCard(page, "TopologyCanvas")

  // When
  const result = await topology.evaluate((card) => {
    const overlaps = (left: DOMRect, right: DOMRect) =>
      left.left < right.right &&
      left.right > right.left &&
      left.top < right.bottom &&
      left.bottom > right.top
    const labels = Array.from(card.querySelectorAll<SVGGraphicsElement>("[data-topology-label]"))
    const nodes = Array.from(card.querySelectorAll<SVGGraphicsElement>(".topologyNode circle"))
    const edges = Array.from(card.querySelectorAll<SVGGraphicsElement>(".topologyEdge"))
    return {
      labelCount: labels.length,
      nodeCount: nodes.length,
      collisions: labels.flatMap((label) => {
        const labelBounds = label.getBoundingClientRect()
        return [...nodes, ...edges].filter((item) =>
          overlaps(labelBounds, item.getBoundingClientRect()),
        )
      }).length,
    }
  })

  // Then
  expect(result.labelCount).toBe(result.nodeCount)
  expect(result.collisions).toBe(0)
})

test("changes real selected DOM state for every interactive primitive", async ({ page }) => {
  // Given
  const topology = stateCard(page, "TopologyCanvas")
  const timeline = stateCard(page, "EventTimeline")
  const metric = stateCard(page, "MetricDelta")
  const patch = stateCard(page, "TypedPatchDiff")
  const evidence = stateCard(page, "EvidenceRail")
  const approval = stateCard(page, "ApprovalEvidence")
  const controls = [
    topology.getByRole("option", { name: "AGG 1, default" }),
    timeline.getByRole("button", { name: "Select event Backhaul utilization high" }),
    metric.getByRole("button", { name: "Select metric P95 DL throughput" }),
    patch.getByRole("button", { name: "Select line 130 Addition" }),
    evidence.getByRole("button", { name: "Select Scenario" }),
    approval.getByRole("button", { name: "Record approval evidence" }),
  ]

  // When / Then
  for (const control of controls) {
    await control.click()
    await expect(control).toBeFocused()
    const selected =
      (await control.getAttribute("aria-selected")) ?? (await control.getAttribute("aria-pressed"))
    expect(selected).toBe("true")
  }
})

test("renders primitive-owned hover active and focus gallery states", async ({ page }) => {
  // Given
  const states = [
    {
      primitive: "TopologyCanvas",
      role: "option",
      hover: "Core DC, approved",
      active: "AGG 1, default",
      focus: "AGG 2, stale",
    },
    {
      primitive: "EventTimeline",
      role: "button",
      hover: "Select event Synthetic scenario started",
      active: "Select event Backhaul utilization high",
      focus: "Select event Backhaul utilization high",
    },
    {
      primitive: "MetricDelta",
      role: "button",
      hover: "Select metric P95 latency",
      active: "Select metric P95 DL throughput",
      focus: "Select metric P95 DL throughput",
    },
    {
      primitive: "TypedPatchDiff",
      role: "button",
      hover: "Select line 130 Removal",
      active: "Select line 130 Addition",
      focus: "Select line 129 Context",
    },
    {
      primitive: "EvidenceRail",
      role: "button",
      hover: "Select Replay hash",
      active: "Select Scenario",
      focus: "Select Generated at",
    },
    {
      primitive: "ApprovalEvidence",
      role: "button",
      hover: "Record approval evidence",
      active: "Record approval evidence",
      focus: "Record rejection evidence",
    },
  ] as const

  for (const state of states) {
    // When
    const defaultControl = stateCard(page, state.primitive).getByRole(state.role, {
      name: state.hover,
    })
    const hoverControl = stateCard(page, state.primitive, "hover").getByRole(state.role, {
      name: state.hover,
    })
    const activeControl = stateCard(page, state.primitive, "active").getByRole(state.role, {
      name: state.active,
    })
    const focusControl = stateCard(page, state.primitive, "focus").getByRole(state.role, {
      name: state.focus,
    })
    const defaultBackground = await defaultControl.evaluate(
      (element) => getComputedStyle(element).backgroundColor,
    )
    const hoverBackground = await hoverControl.evaluate(
      (element) => getComputedStyle(element).backgroundColor,
    )
    await focusControl.focus()

    // Then
    expect(hoverBackground, state.primitive).not.toBe(defaultBackground)
    const selected =
      (await activeControl.getAttribute("aria-selected")) ??
      (await activeControl.getAttribute("aria-pressed"))
    expect(selected).toBe("true")
    await expect(focusControl).toBeFocused()
    expect(
      await focusControl.evaluate((element) =>
        Number.parseFloat(getComputedStyle(element).outlineWidth),
      ),
    ).toBeGreaterThanOrEqual(2)
  }
})

test("has no serious accessibility, global overflow, target, error, or overlay defect", async ({
  page,
}) => {
  // Given / When
  const axe = await new AxeBuilder({ page }).include("#__showcase").analyze()
  const serious = axe.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  )
  const pageAudit = await page.evaluate(() => {
    const visibleTargets = Array.from(
      document.querySelectorAll<HTMLElement>("button:not([disabled]), a[href], input, select"),
    ).filter((element) => {
      const style = getComputedStyle(element)
      const bounds = element.getBoundingClientRect()
      return (
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        bounds.width > 0 &&
        bounds.height > 0 &&
        bounds.bottom > 0 &&
        bounds.top < innerHeight
      )
    })
    return {
      globalOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      shortTargets: visibleTargets
        .filter((element) => element.getBoundingClientRect().height < 44)
        .map((element) => ({
          name: element.getAttribute("aria-label") ?? element.textContent?.trim() ?? "unnamed",
          height: element.getBoundingClientRect().height,
        })),
      overlayCount: document.querySelectorAll(
        "[data-react-scan], [data-react-grab], .react-scan, .react-grab, #react-scan-toolbar",
      ).length,
    }
  })
  const errorCard = stateCard(page, "ErrorState", "error")
  await errorCard.scrollIntoViewIfNeeded()
  const errorAudit = await errorCard.getByRole("alert").evaluate((element) => ({
    clipped: element.scrollWidth > element.clientWidth,
    title: element.querySelector("h3")?.textContent?.trim() ?? "",
    detail: Array.from(element.querySelectorAll("p"), (item) => item.textContent?.trim() ?? ""),
  }))

  // Then
  expect(serious).toEqual([])
  expect(pageAudit.globalOverflow).toBeLessThanOrEqual(0)
  expect(pageAudit.shortTargets).toEqual([])
  expect(pageAudit.overlayCount).toBe(0)
  expect(errorAudit.clipped).toBe(false)
  expect(errorAudit.title).toContain("recovery state")
  expect(errorAudit.detail.join(" ")).toContain("Recovery remains evidence-only")
})

test("opens EvidenceRail in the top layer and restores focus after Escape", async ({ page }) => {
  // Given
  const trigger = page.getByRole("button", { name: "Open selected evidence" })

  // When
  await trigger.click()
  const dialog = page.getByRole("dialog", { name: "Selected evidence" })

  // Then
  await expect(dialog).toBeVisible()
  expect(await dialog.evaluate((element) => element.matches(":modal"))).toBe(true)
  expect(
    await page.evaluate(() => {
      const background = document.querySelector(".showcaseAnchorNav a")
      if (!(background instanceof HTMLElement)) return false
      background.focus()
      return document.activeElement !== background
    }),
  ).toBe(true)

  // When
  await page.keyboard.press("Escape")

  // Then
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
})
