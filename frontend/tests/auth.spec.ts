import { expect, test } from "@playwright/test"
import { adminToken, createNamespace, createTestUser } from "./utils/api.ts"
import { randomEmail, randomPassword } from "./utils/random.ts"
import { loginAs } from "./utils/ui.ts"

test.describe("Authentication flows", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("sign up → login → dashboard → logout", async ({ page }) => {
    const email = randomEmail()
    const password = randomPassword()
    await page.goto("/signup")
    await page.getByTestId("full-name-input").fill("New Person")
    await page.getByTestId("email-input").fill(email)
    await page.getByTestId("password-input").fill(password)
    await page.getByTestId("confirm-password-input").fill(password)
    await page.getByRole("button", { name: "Sign Up" }).click()
    await expect(page).toHaveURL(/\/login$/)

    await loginAs(page, email, password)
    await expect(page.getByTestId("dashboard-greeting")).toContainText("New")
    // a brand-new user has no spaces yet
    await expect(page.getByTestId("namespace-switcher")).toContainText(
      "No spaces yet",
    )
    await page.getByTestId("user-menu").click()
    await page.getByRole("menuitem", { name: "Log out" }).click()
    await expect(page).toHaveURL(/\/login$/)
    await page.goto("/shared")
    await expect(page).toHaveURL(/\/login$/)
  })

  test("wrong password shows an error and keeps you on /login", async ({
    page,
  }) => {
    const user = await createTestUser(page.request)
    await page.goto("/login")
    await page.getByTestId("email-input").fill(user.email)
    await page.getByTestId("password-input").fill("definitely-wrong")
    await page.getByRole("button", { name: "Log In" }).click()
    await expect(page.getByText("Incorrect email or password")).toBeVisible()
    await expect(page).toHaveURL(/\/login$/)
  })

  test("logged-in users are redirected away from /login and /signup", async ({
    page,
  }) => {
    const user = await createTestUser(page.request)
    await loginAs(page, user.email, user.password)
    await page.goto("/login")
    await expect(page).toHaveURL("/")
    await page.goto("/signup")
    await expect(page).toHaveURL("/")
  })

  test("a 401 from the API logs the user out", async ({ page }) => {
    const user = await createTestUser(page.request)
    await loginAs(page, user.email, user.password)
    await page.route("**/api/v1/documents/recent*", (route) =>
      route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Not authenticated" }),
      }),
    )
    await page.goto("/")
    await expect(page).toHaveURL(/\/login$/)
    expect(
      await page.evaluate(() => localStorage.getItem("access_token")),
    ).toBeNull()
  })

  test("a 403 shows the no-access state and does NOT log out", async ({
    page,
  }) => {
    const user = await createTestUser(page.request)
    await loginAs(page, user.email, user.password)
    await page.route("**/api/v1/namespaces/by-slug/*", (route) =>
      route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Not enough permissions" }),
      }),
    )
    await page.goto("/s/some-space")
    await expect(page.getByTestId("no-access")).toBeVisible()
    await expect(page).not.toHaveURL(/\/login/)
    expect(
      await page.evaluate(() => localStorage.getItem("access_token")),
    ).not.toBeNull()
    await page.getByRole("link", { name: "Back to dashboard" }).click()
    await expect(page.getByTestId("dashboard-greeting")).toBeVisible()
  })

  test("a space of another user is reported as not found", async ({ page }) => {
    const admin = await adminToken(page.request)
    const ns = await createNamespace(page.request, admin)
    const user = await createTestUser(page.request)
    await loginAs(page, user.email, user.password)
    await page.goto(`/s/${ns.slug}`)
    await expect(page.getByTestId("not-found-state")).toBeVisible()
  })

  test("a user's password can be changed and the old one stops working", async ({
    page,
  }) => {
    const user = await createTestUser(page.request)
    await loginAs(page, user.email, user.password)
    await page.goto("/settings?tab=password")
    const next = randomPassword()
    await page.getByTestId("current-password-input").fill(user.password)
    await page.getByTestId("new-password-input").fill(next)
    await page.getByTestId("confirm-password-input").fill(next)
    await page.getByRole("button", { name: "Update Password" }).click()
    await expect(page.getByText("Password updated successfully")).toBeVisible()
    const old = await page.request.post(
      `${process.env.VITE_API_URL}/api/v1/login/access-token`,
      { form: { username: user.email, password: user.password } },
    )
    expect(old.status()).toBe(400)
    const fresh = await page.request.post(
      `${process.env.VITE_API_URL}/api/v1/login/access-token`,
      { form: { username: user.email, password: next } },
    )
    expect(fresh.ok()).toBeTruthy()
  })
})
