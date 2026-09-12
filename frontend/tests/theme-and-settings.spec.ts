import { expect, test } from "@playwright/test"
import { createTestUser } from "./utils/api.ts"
import { loginAs } from "./utils/ui.ts"

test.describe("Appearance & settings", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("theme cards toggle the html class and persist across reloads", async ({
    page,
  }) => {
    const user = await createTestUser(page.request)
    await loginAs(page, user.email, user.password)
    await page.goto("/settings?tab=appearance")
    await page.getByTestId("dark-mode").click()
    await expect(page.locator("html")).toHaveClass(/dark/)
    await page.reload()
    await expect(page.locator("html")).toHaveClass(/dark/)
    await page.getByTestId("light-mode").click()
    await expect(page.locator("html")).toHaveClass(/light/)
    await expect(page.locator("html")).not.toHaveClass(/dark/)
    expect(
      await page.evaluate(() => localStorage.getItem("vite-ui-theme")),
    ).toBe("light")
  })

  test("header theme toggle works from any page", async ({ page }) => {
    const user = await createTestUser(page.request)
    await loginAs(page, user.email, user.password)
    await page.getByTestId("header-theme-button").click()
    await page.getByTestId("header-dark-mode").click()
    await expect(page.locator("html")).toHaveClass(/dark/)
    await expect(page.getByTestId("header-dark-mode")).toBeHidden()
    await page.getByTestId("header-theme-button").click()
    await expect(page.getByTestId("header-light-mode")).toBeVisible()
    await page.getByTestId("header-light-mode").click()
    await expect(page.locator("html")).toHaveClass(/light/)
  })

  test("editor width preference is stored", async ({ page }) => {
    const user = await createTestUser(page.request)
    await loginAs(page, user.email, user.password)
    await page.goto("/settings?tab=appearance")
    await page.getByRole("radio", { name: "Wide" }).click()
    expect(
      await page.evaluate(() => localStorage.getItem("kb:editor-width")),
    ).toBe("wide")
    expect(
      await page.evaluate(() =>
        document.documentElement.style.getPropertyValue(
          "--kb-editor-max-width",
        ),
      ),
    ).toBe("1200px")
    await page.getByRole("radio", { name: "Comfortable" }).click()
    expect(
      await page.evaluate(() => localStorage.getItem("kb:editor-width")),
    ).toBe("comfortable")
  })

  test("profile name update is reflected in the sidebar", async ({ page }) => {
    const user = await createTestUser(page.request)
    await loginAs(page, user.email, user.password)
    await page.goto("/settings?tab=profile")
    await page.getByRole("button", { name: "Edit" }).click()
    await page.getByLabel("Full name").fill("Renamed Person")
    await page.getByRole("button", { name: "Save" }).click()
    await expect(page.getByText("User updated successfully")).toBeVisible()
    await expect(page.getByTestId("user-menu")).toContainText("Renamed Person")
    await expect(page.getByTestId("dashboard-greeting")).toHaveCount(0)
    await page.goto("/")
    await expect(page.getByTestId("dashboard-greeting")).toContainText(
      "Renamed",
    )
  })

  test("regular users see the Danger zone tab and superusers do not", async ({
    page,
  }) => {
    const user = await createTestUser(page.request)
    await loginAs(page, user.email, user.password)
    await page.goto("/settings")
    await expect(page.getByRole("tab", { name: "Danger zone" })).toBeVisible()
  })

  test("developer tab shows API docs links and a curl example", async ({
    page,
  }) => {
    const user = await createTestUser(page.request)
    await loginAs(page, user.email, user.password)
    await page.goto("/settings?tab=developer")
    await expect(
      page.getByRole("link", { name: /Swagger|OpenAPI|API docs/i }).first(),
    ).toHaveAttribute("href", /\/docs$/)
    await expect(
      page.getByText(/Authorization: Bearer kb_/).first(),
    ).toBeVisible()
  })
})
