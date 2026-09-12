import { expect, type Page } from "@playwright/test"
import { verificationToken } from "./mail.ts"
import { enterTwoFactorCode } from "./ui.ts"

/**
 * Register through the form and then follow the confirmation link, because an
 * account whose address is unconfirmed cannot sign in.
 */
export async function signUpNewUser(
  page: Page,
  name: string,
  email: string,
  password: string,
) {
  await page.goto("/signup")

  await page.getByTestId("full-name-input").fill(name)
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByTestId("confirm-password-input").fill(password)
  await page.getByRole("button", { name: "Sign Up" }).click()
  await expect(page.getByTestId("check-your-inbox")).toBeVisible()

  await confirmEmail(page, email)
}

/** Open the emailed confirmation link, as the new account holder would. */
export async function confirmEmail(page: Page, email: string) {
  const token = await verificationToken(page.request, email)
  await page.goto(`/verify-email?token=${token}`)
  await expect(page.getByTestId("verify-email-success")).toBeVisible()
}

export async function logInUser(page: Page, email: string, password: string) {
  await page.goto("/login")

  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await enterTwoFactorCode(page, email)
  await page.waitForURL("/")
  await expect(page.getByTestId("dashboard-greeting")).toBeVisible()
}

export async function logOutUser(page: Page) {
  await page.getByTestId("user-menu").click()
  await page.getByRole("menuitem", { name: "Log out" }).click()
  await page.goto("/login")
}
