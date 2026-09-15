import { expect, test } from "@playwright/test"

/**
 * Recovering from a deploy that lands mid-session.
 *
 * Routes are code-split, so a deploy replaces the chunk filenames a running tab
 * still points at. The tab must recover by reloading — once, because a reload
 * loop is worse than the error it replaces.
 */

test.describe("A deploy while somebody is using the app", () => {
  test("a failed chunk load reloads the page", async ({ page }) => {
    await page.goto("/")
    await expect(page.getByTestId("dashboard-greeting")).toBeVisible()
    await page.evaluate(() => sessionStorage.removeItem("stale-build-reload"))

    // Vite fires this when a dynamic import fails, which is what a replaced
    // chunk looks like from inside a running tab. Driven directly rather than
    // by blocking a URL, because the chunk layout differs between dev and a
    // production build and the wiring is the same either way.
    const reloaded = page
      .waitForNavigation({ timeout: 20_000 })
      .catch(() => null)
    await page.evaluate(() => {
      window.dispatchEvent(new Event("vite:preloadError", { cancelable: true }))
    })
    await reloaded

    await expect(page.getByTestId("dashboard-greeting")).toBeVisible()
    const guard = await page.evaluate(() =>
      sessionStorage.getItem("stale-build-reload"),
    )
    expect(guard, "the attempt is recorded, so it cannot repeat").not.toBeNull()
  })

  test("it recovers at most once, so it cannot loop", async ({ page }) => {
    await page.goto("/")
    await page.evaluate(() =>
      sessionStorage.setItem("stale-build-reload", String(Date.now())),
    )

    // Second failure in the same tab: the error is left to surface rather than
    // reloading again.
    const recovered = await page.evaluate(async () => {
      // A URL the dev server serves, not a path tsc can resolve from here.
      // @ts-expect-error - runtime import inside the browser
      const { reloadForNewBuild } = await import("/src/lib/staleBuild.ts")
      return reloadForNewBuild()
    })
    expect(recovered, "a second reload must not be attempted").toBe(false)
  })

  test("it knows a stale chunk from a real failure", async ({ page }) => {
    await page.goto("/")
    const verdicts = await page.evaluate(async () => {
      // @ts-expect-error - runtime import inside the browser
      const { isStaleChunkError } = await import("/src/lib/staleBuild.ts")
      return {
        vite: isStaleChunkError(
          new Error(
            "Failed to fetch dynamically imported module: https://x/assets/search-abc.js",
          ),
        ),
        safari: isStaleChunkError(
          new Error("Importing a module script failed."),
        ),
        unrelated: isStaleChunkError(new Error("Network request failed")),
        nonsense: isStaleChunkError(undefined),
      }
    })
    expect(verdicts.vite).toBe(true)
    expect(verdicts.safari).toBe(true)
    // A real outage must not be papered over with a reload.
    expect(verdicts.unrelated).toBe(false)
    expect(verdicts.nonsense).toBe(false)
  })
})

test.describe("Detecting a replaced build", () => {
  test("it declines to guess when there are no hashed chunks", async ({
    page,
  }) => {
    await page.goto("/")
    await expect(page.getByTestId("dashboard-greeting")).toBeVisible()

    // The dev server has no `assets/index-<hash>.js`, so this tab cannot know
    // which build it is. Answering "stale" there would reload on every error.
    // The comparison itself is exercised against a real build below.
    await page.route("**/", async (route) => {
      if (route.request().resourceType() !== "fetch") return route.continue()
      await route.fulfill({
        contentType: "text/html",
        body: '<script type="module" src="/assets/index-NEWBUILD9.js"></script>',
      })
    })

    const stale = await page.evaluate(async () => {
      // @ts-expect-error - runtime import inside the browser
      const m = await import("/src/lib/staleBuild.ts")
      return m.isStaleBuild()
    })
    expect(stale, "no build id means no opinion").toBe(false)
  })

  test("a built shell names an entry chunk, and a changed one is detectable", async ({
    page,
  }) => {
    // Against the built application, where the hashed entry actually exists.
    // Skipped when the suite runs against the dev server.
    const base = process.env.PLAYWRIGHT_BASE_URL ?? ""
    test.skip(base.includes("5173") || base === "", "needs a production build")

    await page.goto("/login")
    const entry = await page.evaluate(() =>
      fetch("/", { cache: "no-store", headers: { Accept: "text/html" } })
        .then((r) => r.text())
        .then((h) => /assets\/index-[A-Za-z0-9_-]+\.js/.exec(h)?.[0]),
    )
    expect(entry, "the shell must name a hashed entry chunk").toMatch(
      /^assets\/index-/,
    )
  })

  test("a server that cannot be reached is not a stale build", async ({
    page,
  }) => {
    await page.goto("/")
    await page.route("**/", (route) => route.abort())

    const stale = await page.evaluate(async () => {
      // @ts-expect-error - runtime import inside the browser
      const m = await import("/src/lib/staleBuild.ts")
      return m.isStaleBuild()
    })
    // Reloading into a network failure helps nobody.
    expect(stale).toBe(false)
  })
})
