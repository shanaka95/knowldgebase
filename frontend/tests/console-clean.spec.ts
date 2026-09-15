import { expect, test } from "@playwright/test"

/**
 * Pages must render without React complaining.
 *
 * Duplicate keys are the one to care about: React says plainly that children
 * "may be duplicated and/or omitted — the behavior is unsupported", and an
 * omitted child is how a list of search suggestions turns into a crash
 * somewhere else entirely. A warning in the console is the only notice given
 * before that happens, so it is treated as a failure here.
 */

const ROUTES = [
  "/search?q=",
  "/search",
  "/usage",
  "/usage?from=",
  "/ask",
  "/",
  "/shared",
  "/capture",
  "/admin?tab=users",
  "/admin?tab=groups",
  "/admin?tab=usage",
  "/settings",
]

test("no React key or render warnings on any main screen", async ({ page }) => {
  const complaints: string[] = []
  page.on("console", (message) => {
    if (message.type() !== "error" && message.type() !== "warning") return
    const text = message.text()
    if (
      /same key|unique "key"|Each child in a list|Warning: Failed prop|validateDOMNesting/i.test(
        text,
      )
    ) {
      complaints.push(text.slice(0, 200))
    }
  })
  const crashes: string[] = []
  page.on("pageerror", (error) => crashes.push(error.message))

  for (const route of ROUTES) {
    await page.goto(route, { waitUntil: "networkidle" })
    await page.waitForTimeout(250)
    await expect(page.getByTestId("route-error")).toHaveCount(0)
  }

  expect(crashes, "a page threw while rendering").toEqual([])
  expect(complaints, "React complained about the markup").toEqual([])
})
