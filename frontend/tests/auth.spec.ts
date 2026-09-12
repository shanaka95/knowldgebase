import { expect, test } from "@playwright/test"
import {
  API,
  adminToken,
  createNamespace,
  createTestUser,
} from "./utils/api.ts"
import { passwordResetToken, twoFactorCode } from "./utils/mail.ts"
import { randomEmail, randomPassword } from "./utils/random.ts"
import { enterTwoFactorCode, loginAs } from "./utils/ui.ts"
import { confirmEmail } from "./utils/user.ts"

test.describe("Authentication flows", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("sign up → confirm → login → dashboard → logout", async ({ page }) => {
    const email = randomEmail()
    const password = randomPassword()
    await page.goto("/signup")
    await page.getByTestId("full-name-input").fill("New Person")
    await page.getByTestId("email-input").fill(email)
    await page.getByTestId("password-input").fill(password)
    await page.getByTestId("confirm-password-input").fill(password)
    await page.getByRole("button", { name: "Sign Up" }).click()

    // Registering never signs anyone in — it asks them to read their mail.
    await expect(page.getByTestId("check-your-inbox")).toBeVisible()
    expect(
      await page.evaluate(() => localStorage.getItem("access_token")),
    ).toBeNull()

    await confirmEmail(page, email)

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
    await expect(page.getByTestId("code-input")).toHaveCount(0)
    await expect(page).toHaveURL(/\/login$/)
  })

  test("an unconfirmed address cannot sign in and can ask for a new link", async ({
    page,
  }) => {
    const user = await createTestUser(page.request, { is_verified: false })
    await page.goto("/login")
    await page.getByTestId("email-input").fill(user.email)
    await page.getByTestId("password-input").fill(user.password)
    await page.getByRole("button", { name: "Log In" }).click()

    await expect(
      page.getByText("Confirm your email address before signing in."),
    ).toBeVisible()
    await page.getByTestId("resend-confirmation").click()
    await expect(
      page.getByText("If that address has an account, we have sent a message"),
    ).toBeVisible()

    // and the link that was sent does confirm the address
    await confirmEmail(page, user.email)
    await loginAs(page, user.email, user.password)
  })

  test("a wrong code is refused and says how many attempts are left", async ({
    page,
  }) => {
    const user = await createTestUser(page.request)
    await page.goto("/login")
    await page.getByTestId("email-input").fill(user.email)
    await page.getByTestId("password-input").fill(user.password)
    await page.getByRole("button", { name: "Log In" }).click()

    const codeInput = page.getByTestId("code-input")
    await expect(codeInput).toBeVisible()
    await expect(page.getByText(/We sent a code to/)).toBeVisible()

    // a full-length code auto-submits, so a wrong one is answered immediately
    await codeInput.fill("000000")
    await expect(page.getByText(/That code is not right\./)).toBeVisible()
    await expect(page).toHaveURL(/\/login$/)

    // the real one still works
    await enterTwoFactorCode(page, user.email)
    await page.waitForURL("/")
  })

  test("a fresh code can be requested, and Back discards the challenge", async ({
    page,
  }) => {
    // the resend button holds a real cooldown, so this one waits out 30 seconds
    test.setTimeout(90_000)
    const user = await createTestUser(page.request)
    await page.goto("/login")
    await page.getByTestId("email-input").fill(user.email)
    await page.getByTestId("password-input").fill(user.password)
    await page.getByRole("button", { name: "Log In" }).click()

    const first = await twoFactorCode(page.request, user.email)
    // the resend button holds a short cooldown after each send
    const resend = page.getByTestId("resend-code")
    await expect(resend).toBeDisabled()
    await expect(resend).toBeEnabled({ timeout: 45_000 })
    await resend.click()

    const second = await twoFactorCode(page.request, user.email, { not: first })
    expect(second).not.toBe(first)

    await page.getByTestId("back-to-password").click()
    await expect(page.getByTestId("code-input")).toHaveCount(0)
    await expect(page.getByTestId("password-input")).toBeVisible()

    // nothing about the abandoned challenge is kept anywhere
    expect(
      await page.evaluate(() => JSON.stringify(localStorage)),
    ).not.toContain("challenge")
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

    // the change revokes every token issued before it, this one included, so
    // the reply carries a replacement: the user must still be signed in here
    await page.goto("/")
    await expect(page.getByTestId("dashboard-greeting")).toBeVisible()

    const old = await page.request.post(`${API}/login/access-token`, {
      form: { username: user.email, password: user.password },
    })
    expect(old.status()).toBe(400)
    const fresh = await page.request.post(`${API}/login/access-token`, {
      form: { username: user.email, password: next },
    })
    expect(fresh.ok()).toBeTruthy()
    // still only a challenge, never a session
    expect(await fresh.json()).not.toHaveProperty("access_token")
  })

  test("a forgotten password can be reset from the emailed link", async ({
    page,
  }) => {
    const user = await createTestUser(page.request)
    await page.goto("/login")
    await expect(
      page.getByRole("link", { name: "Forgot your password?" }),
    ).toHaveAttribute("href", "/forgot-password")

    await page.goto("/forgot-password")
    await expect(
      page.getByRole("heading", { name: "Forgot your password?" }),
    ).toBeVisible()
    await page.getByTestId("email-input").fill(user.email)
    await page.getByRole("button", { name: "Send the link" }).click()
    await expect(
      page.getByText("If that address has an account, we have sent a message"),
    ).toBeVisible()

    const token = await passwordResetToken(page.request, user.email)
    const next = randomPassword()
    await page.goto(`/reset-password?token=${token}`)
    await expect(
      page.getByRole("heading", { name: "Choose a new password" }),
    ).toBeVisible()
    await page.getByTestId("new-password-input").fill(next)
    await page.getByTestId("confirm-password-input").fill(next)
    await page.getByRole("button", { name: "Set the new password" }).click()
    await expect(page.getByTestId("reset-success")).toBeVisible()

    await loginAs(page, user.email, next)
  })

  test("an unknown address is answered exactly like a known one", async ({
    page,
  }) => {
    await page.goto("/forgot-password")
    await expect(
      page.getByRole("heading", { name: "Forgot your password?" }),
    ).toBeVisible()
    await page.getByTestId("email-input").fill(randomEmail())
    await page.getByRole("button", { name: "Send the link" }).click()
    await expect(
      page.getByText("If that address has an account, we have sent a message"),
    ).toBeVisible()
  })

  test("signing out everywhere ends this session too", async ({ page }) => {
    const user = await createTestUser(page.request)
    await loginAs(page, user.email, user.password)
    await page.goto("/settings?tab=password")
    await page.getByTestId("sign-out-everywhere").click()
    await page.getByTestId("confirm-sign-out-everywhere").click()
    await expect(page).toHaveURL(/\/login$/)
    expect(
      await page.evaluate(() => localStorage.getItem("access_token")),
    ).toBeNull()
  })
})
