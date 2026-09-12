import { test as setup } from "@playwright/test"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { enterTwoFactorCode } from "./utils/ui.ts"

const authFile = "playwright/.auth/user.json"

setup("authenticate", async ({ page }) => {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(firstSuperuser)
  await page.getByTestId("password-input").fill(firstSuperuserPassword)
  await page.getByRole("button", { name: "Log In" }).click()
  // Signing in is two steps: the password, then the code that was emailed.
  await enterTwoFactorCode(page, firstSuperuser)
  await page.waitForURL("/")
  await page.context().storageState({ path: authFile })
})
