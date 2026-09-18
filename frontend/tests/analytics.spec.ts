/**
 * The tag manager is installed, on every route.
 *
 * Worth a test because of how it fails: an edit to `index.html` that drops the
 * snippet breaks nothing, logs nothing and looks exactly like a working site.
 * The first sign is a month of missing numbers.
 *
 * Asserted on what is local - the snippet's own effects - and never on a
 * request to googletagmanager.com, so the suite does not need the internet and
 * a test run does not report itself as traffic.
 */

import { expect, test } from "@playwright/test"

const CONTAINER = "GTM-PF2P5NDT"

test("every route loads the tag manager", async ({ page }) => {
  // The application is a single page: /notes and /search are the same shell as
  // /, so this is really one assertion made three times. It is made three
  // times anyway, because "all pages" is the requirement.
  for (const route of ["/", "/search", "/notes"]) {
    await page.goto(route)
    const layer = await page.evaluate(
      () =>
        (window as unknown as { dataLayer?: Record<string, unknown>[] })
          .dataLayer ?? null,
    )
    expect(layer, `no dataLayer on ${route}`).not.toBeNull()
    expect(
      layer?.some((entry) => entry.event === "gtm.js"),
      `the container never started on ${route}`,
    ).toBe(true)
  }
})

test("the shell names the container we meant to load", async ({ request }) => {
  // A wrong id is the other silent failure: everything loads, nothing lands in
  // the account anybody is looking at.
  const shell = await request.get("/")
  expect(await shell.text()).toContain(CONTAINER)
})
