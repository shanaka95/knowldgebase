import { expect, test } from "@playwright/test"

import { API, adminToken, auth, uid } from "./utils/api.ts"
import { createUser } from "./utils/privateApi"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser } from "./utils/user"

/**
 * The two dashboards, and the line between them.
 *
 * The case that matters most is the last one: an ordinary account's page must
 * not show money anywhere, and the reply behind it has no field to carry it.
 */

test.setTimeout(120_000)

test.describe("My usage", () => {
  test("the page renders with a range and an empty state", async ({ page }) => {
    await page.goto("/usage")

    await expect(page.getByTestId("my-usage")).toBeVisible()
    await expect(page.getByTestId("range-picker")).toBeVisible()
    // Four activity cards, whether or not anything has happened yet.
    await expect(page.getByTestId("usage-count-ask")).toBeVisible()
    await expect(page.getByTestId("usage-count-search")).toBeVisible()
  })

  test("a range preset lands in the URL and survives a reload", async ({
    page,
  }) => {
    await page.goto("/usage")
    await page.getByTestId("range-7").click()

    await expect(page).toHaveURL(/from=\d{4}-\d{2}-\d{2}/)
    await expect(page).toHaveURL(/to=\d{4}-\d{2}-\d{2}/)

    const url = page.url()
    await page.reload()
    expect(page.url()).toBe(url)
    await expect(page.getByTestId("my-usage")).toBeVisible()
  })

  test("a search shows up as activity", async ({ page, request }) => {
    // Driven through the API as the same account the browser is signed in as.
    // A search is counted the moment it is run, whether or not the index has
    // anything to return - which is the behaviour worth pinning down, and it
    // does not depend on this machine having an embedding server.
    const token = await adminToken(request)
    const searched = await request.get(
      `${API}/search/retrieve?q=usage+probe+${uid()}`,
      { headers: auth(token) },
    )
    expect([200, 500, 502, 503]).toContain(searched.status())

    await page.goto("/usage")
    const searches = page.getByTestId("usage-count-search")
    await expect(searches).toBeVisible()
    await expect(searches).not.toHaveText(/^0/)
  })

  test("Usage is reachable from the sidebar", async ({ page }) => {
    await page.goto("/")
    await page.getByRole("link", { name: "Usage" }).first().click()
    await expect(page).toHaveURL(/\/usage/)
  })
})

test.describe("Admin usage", () => {
  test("the tab shows spend and a breakdown by account", async ({ page }) => {
    await page.goto("/admin?tab=usage")

    await expect(page.getByTestId("admin-usage")).toBeVisible()
    await expect(page.getByTestId("usage-total-cost")).toBeVisible()
    // Cost is a dollar figure, which is the whole reason this tab exists.
    await expect(page.getByTestId("usage-total-cost")).toContainText("$")
  })

  test("the breakdown can be switched between dimensions", async ({ page }) => {
    await page.goto("/admin?tab=usage")

    for (const by of ["group", "model", "feature", "user"]) {
      await page.getByTestId(`usage-by-${by}`).click()
      await expect(page.getByTestId(`usage-by-${by}`)).toHaveAttribute(
        "data-state",
        "active",
      )
    }
  })

  test("changing tab keeps the rest of the URL", async ({ page }) => {
    // The admin route used to replace its whole search object on a tab change,
    // which would drop any parameter a panel had put there.
    await page.goto("/admin?tab=usage&from=2026-01-01")
    await page.getByRole("tab", { name: "Groups" }).click()

    await expect(page).toHaveURL(/tab=groups/)
    await expect(page).toHaveURL(/from=2026-01-01/)
  })
})

test.describe("Cost stays on the admin side", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("an ordinary account is never shown what it cost", async ({ page }) => {
    const email = randomEmail()
    const password = randomPassword()
    await createUser({ email, password })

    // Nothing the browser receives while they read their own usage may carry a
    // cost figure.
    const leaked: string[] = []
    page.on("response", async (response) => {
      if (!response.url().includes("/api/v1/usage")) return
      try {
        const body = await response.text()
        if (/cost/i.test(body)) leaked.push(response.url())
      } catch {
        /* a redirect, or a body already consumed */
      }
    })

    await logInUser(page, email, password)
    await page.goto("/usage")
    await expect(page.getByTestId("my-usage")).toBeVisible()
    await page.waitForLoadState("networkidle")

    expect(leaked, "a usage reply carried a cost figure").toEqual([])
    await expect(page.getByTestId("my-usage")).not.toContainText("$")

    // And the administration of it is closed to them entirely.
    await page.goto("/admin?tab=usage")
    await expect(page.getByTestId("admin-usage")).toHaveCount(0)
    await expect(page).not.toHaveURL(/\/admin/)
  })

  test("the admin endpoints refuse an ordinary account outright", async ({
    request,
  }) => {
    const email = randomEmail()
    const password = randomPassword()
    await createUser({ email, password })
    const admin = await adminToken(request)

    // The superuser can read it...
    const allowed = await request.get(`${API}/admin/usage/summary`, {
      headers: auth(admin),
    })
    expect(allowed.ok(), await allowed.text()).toBeTruthy()
    expect(await allowed.text()).toContain("cost_nanos")

    // ...and the account whose usage it is cannot.
    const token = await (async () => {
      const { getToken } = await import("./utils/api.ts")
      return getToken(request, email, password)
    })()
    const refused = await request.get(`${API}/admin/usage/summary`, {
      headers: auth(token),
    })
    expect(refused.status()).toBe(403)
  })
})
