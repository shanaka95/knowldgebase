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

/**
 * The cost of cancelling `vite:preloadError`.
 *
 * Vite's preload helper is, in full:
 *
 * ```js
 * const onError = (err) => {
 *   const e = new Event("vite:preloadError", { cancelable: true })
 *   e.payload = err
 *   window.dispatchEvent(e)
 *   if (!e.defaultPrevented) throw err
 * }
 * return deps.then(() => importer().catch(onError))
 * ```
 *
 * Cancel that event and `onError` returns rather than throws, so the import
 * *resolves* — with `undefined`. The router reads `component` off it and a
 * momentary network failure becomes a permanent
 * "Cannot read properties of undefined (reading 'component')" on a page whose
 * chunks are all present. These tests run that helper's own logic, because
 * asserting on `defaultPrevented` alone would not show what it costs.
 */
test.describe("A preload failure nobody is going to reload for", () => {
  const VITE_HELPER = `
    const onError = (err) => {
      const e = new Event("vite:preloadError", { cancelable: true })
      e.payload = err
      window.dispatchEvent(e)
      if (!e.defaultPrevented) throw err
    }
  `

  test("is left to reject, not turned into an undefined module", async ({
    page,
  }) => {
    await page.goto("/")
    await expect(page.getByTestId("dashboard-greeting")).toBeVisible()

    const outcome = await page.evaluate(async (helper) => {
      // Cooldown on: this tab has already tried a reload, so nothing is going
      // to rescue this import. It must surface as an error.
      sessionStorage.setItem("stale-build-reload", String(Date.now()))
      const onError = new Function(`${helper}; return onError`)() as (
        e: unknown,
      ) => never
      return Promise.reject(
        new Error(
          "Failed to fetch dynamically imported module: /assets/search-abc.js",
        ),
      )
        .catch(onError)
        .then(
          (module) => (module === undefined ? "resolved undefined" : "loaded"),
          () => "rejected",
        )
    }, VITE_HELPER)

    expect(
      outcome,
      "swallowing it hands the router `undefined` to read `component` off",
    ).toBe("rejected")
  })

  test("a stylesheet that would not load is still survivable", async ({
    page,
  }) => {
    await page.goto("/")
    await expect(page.getByTestId("dashboard-greeting")).toBeVisible()

    // The only dependency Vite waits on is a stylesheet, and it reports that
    // through the same event. Letting it throw would cost the whole route for
    // a missing stylesheet, so this one is swallowed even on cooldown.
    const cancelled = await page.evaluate(() => {
      sessionStorage.setItem("stale-build-reload", String(Date.now()))
      const event = new Event("vite:preloadError", { cancelable: true })
      Object.assign(event, {
        payload: new Error("Unable to preload CSS for /assets/index-abc.css"),
      })
      window.dispatchEvent(event)
      return event.defaultPrevented
    })

    expect(cancelled).toBe(true)
  })
})

/**
 * Recovering from a failure the browser has cached.
 *
 * Assets are served `immutable`, which asks the browser never to revalidate
 * them. The origin used to send that on its 404s and 502s too, and a deploy has
 * a few seconds with no upstream — so a request made at the wrong moment left a
 * year-long "this chunk does not exist" that a reload could not dislodge, on a
 * filename the next build still used. Recovery therefore escalates: reload,
 * then repair the cache and reload, then stop and say what happened.
 */
test.describe("Recovery escalates rather than repeating", () => {
  const CHUNK = new Error(
    "Failed to fetch dynamically imported module: /assets/search-abc123.js",
  )

  test("the second attempt refetches past the cache, then reloads", async ({
    page,
  }) => {
    await page.goto("/")
    await expect(page.getByTestId("dashboard-greeting")).toBeVisible()

    // The reload is real - `window.location.reload` cannot be redefined in
    // Chrome, and stubbing it would test the stub. So what happened is recorded
    // in `sessionStorage`, which survives the reload and can be read after it.
    const navigated = page
      .waitForNavigation({ timeout: 20_000 })
      .catch(() => null)
    await page.evaluate((message) => {
      // A tab that has already reloaded once: the cheap step is spent, so the
      // next failure must reach for the expensive one.
      sessionStorage.setItem("stale-build-reload", String(Date.now()))
      sessionStorage.removeItem("stale-build-repaired")
      sessionStorage.setItem("test-refetched", "[]")

      // `cache: "reload"` is the whole point - it is the only request that goes
      // past the cache and writes what it finds back over it.
      const real = window.fetch
      window.fetch = (input, init) => {
        if (init?.cache === "reload") {
          const seen = JSON.parse(
            sessionStorage.getItem("test-refetched") ?? "[]",
          )
          seen.push(String(input))
          sessionStorage.setItem("test-refetched", JSON.stringify(seen))
        }
        return real(input, init)
      }

      // Not awaited: it ends by reloading, which would destroy this context.
      // @ts-expect-error - runtime import inside the browser
      void import("/src/lib/staleBuild.ts").then((m) =>
        m.recoverFromStaleBuild(new Error(message)),
      )
    }, CHUNK.message)
    await navigated

    await expect(page.getByTestId("dashboard-greeting")).toBeVisible()
    const refetched = await page.evaluate(() =>
      JSON.parse(sessionStorage.getItem("test-refetched") ?? "[]"),
    )
    expect(
      (refetched as string[]).some((url) => url.includes("search-abc123.js")),
      `the failed chunk is refetched past the cache (saw ${JSON.stringify(refetched)})`,
    ).toBe(true)
    const repaired = await page.evaluate(() =>
      sessionStorage.getItem("stale-build-repaired"),
    )
    expect(
      repaired,
      "and the repair is spent, so it cannot loop",
    ).not.toBeNull()
  })

  test("a third failure stops, so the page says what happened", async ({
    page,
  }) => {
    await page.goto("/")
    await page.evaluate(() => {
      sessionStorage.setItem("stale-build-reload", String(Date.now()))
      sessionStorage.setItem("stale-build-repaired", String(Date.now()))
    })

    const recovering = await page.evaluate(async (message) => {
      // @ts-expect-error - runtime import inside the browser
      const { recoverFromStaleBuild } = await import("/src/lib/staleBuild.ts")
      return recoverFromStaleBuild(new Error(message))
    }, CHUNK.message)

    // Both steps are spent. Saying "Updating" now would be a claim that nothing
    // is going to make good on — which is exactly what left the page showing
    // "A new version was released. Loading it now…" indefinitely.
    expect(recovering).toBe(false)
  })
})

test.describe("The page never parks on a promise it cannot keep", () => {
  test("a chunk that will not load, with recovery spent, says so", async ({
    page,
  }) => {
    // Both steps already used, which is the state a tab is in by the time
    // somebody is watching it fail. Set before any script runs, because the
    // error boundary consults them on its first render.
    await page.addInitScript(() => {
      sessionStorage.setItem("stale-build-reload", String(Date.now()))
      sessionStorage.setItem("stale-build-repaired", String(Date.now()))
    })

    // Break the route's own chunk, so the import genuinely fails rather than
    // the state being simulated. Matched in both shapes: the dev server splits
    // routes with a query, a build splits them into hashed files.
    await page.route("**/*", (route) => {
      const url = route.request().url()
      const isSearchChunk =
        (/tsr-split/.test(url) && /search/.test(url)) ||
        /\/assets\/search-[A-Za-z0-9_-]+\.js/.test(url)
      return isSearchChunk ? route.abort("failed") : route.continue()
    })

    await page.goto("/search?q=")

    // The reported bug: "Updating — A new version was released. Loading it
    // now…" with nothing loading and no way out. Nothing is going to reload, so
    // the page must not claim otherwise.
    //
    // Comfortably under the 15s safety timer, deliberately. That timer is a
    // backstop for a reload that was started and did not arrive; if it is what
    // rescues this page, the boundary decided to show "Updating" without
    // checking - which is the bug - and a generous timeout here would hide it.
    await expect(page.getByTestId("route-error")).toBeVisible({
      timeout: 8_000,
    })
    await expect(page.getByTestId("route-updating")).toHaveCount(0)
    await expect(page.getByTestId("route-error-reload")).toBeVisible()
  })
})
