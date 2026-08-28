import { expect, test } from "@playwright/test"

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto("/__showcase")
  await expect(
    page.getByRole("heading", { name: "Evidence-first console primitives" }),
  ).toBeVisible()
})

test("opens EvidenceRail in the top layer and restores focus after Escape", async ({ page }) => {
  const trigger = page.getByRole("button", { name: "Open selected evidence" })

  await trigger.click()
  const dialog = page.getByRole("dialog", { name: "Selected evidence" })

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

  await page.keyboard.press("Escape")

  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
})
