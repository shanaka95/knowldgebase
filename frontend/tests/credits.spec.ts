import { expect, test } from "@playwright/test"

import { API, adminToken, auth, uid } from "./utils/api.ts"
import { createUser } from "./utils/privateApi"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser } from "./utils/user"

/**
 * Credits: what an account has left, and how an administrator changes it.
 *
 * The balance is derived from usage rather than stored, so the thing worth
 * checking through the interface is that a grant lands immediately and that
 * the two screens agree.
 */

test.setTimeout(120_000)

test.describe("Credits", () => {
  test("the usage page leads with what is left", async ({ page }) => {
    await page.goto("/usage")

    const card = page.getByTestId("credit-balance")
    await expect(card).toBeVisible()
    await expect(page.getByTestId("credits-remaining")).toBeVisible()
    // The exchange rate is stated where the number is, not in a help page.
    await expect(card).toContainText(
      "One credit is a thousand tokens, ten embeddings, or ten rerank calls",
    )
    // A credit is what you may spend, not what it cost us.
    await expect(card).not.toContainText("$")
  })

  test("an administrator can grant credits, and they land at once", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const email = randomEmail()
    const user = await createUser({ email, password: randomPassword() })

    const before = await request.get(`${API}/admin/credits/${user.id}`, {
      headers: auth(token),
    })
    expect(before.ok(), await before.text()).toBeTruthy()
    const granted = (await before.json()).granted

    await page.goto("/admin?tab=users")
    const row = page.getByRole("row").filter({ hasText: email })
    await expect(row).toBeVisible()
    await row.getByRole("button").last().click()
    await page.getByTestId("edit-credits").click()

    const dialog = page.getByTestId("credits-dialog")
    await expect(dialog).toBeVisible()
    await dialog.getByTestId("grant-amount").fill("750")
    await dialog.getByTestId("grant-reason").fill(`Backlog ${uid()}`)
    await dialog.getByTestId("grant-submit").click()

    await expect(dialog.getByTestId("grant-row")).toHaveCount(1)
    await expect(dialog.getByTestId("grant-row")).toContainText("750")

    const after = await request.get(`${API}/admin/credits/${user.id}`, {
      headers: auth(token),
    })
    expect((await after.json()).granted).toBe(granted + 750)
  })

  test("the allowance is set per group, alongside the other limits", async ({
    page,
  }) => {
    const name = `Credited ${uid()}`
    await page.goto("/admin?tab=groups")
    await page.getByTestId("new-group").click()
    await page.getByTestId("group-name").fill(name)

    // The field draws itself from the registry; it is not hand-written.
    const card = page.getByTestId("new-group-card")
    await expect(card.getByTestId("limit-monthly_credits")).toBeVisible()
    await card.getByTestId("limit-monthly_credits").fill("25000")
    await page.getByTestId("create-group").click()

    const made = page.getByTestId("group-card").filter({ hasText: name })
    await expect(made.getByTestId("limit-monthly_credits")).toHaveValue("25000")
  })
})

test.describe("Running out", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("an account with no credits is told, and reading still works", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const email = randomEmail()
    const password = randomPassword()
    const user = await createUser({ email, password })

    // Nothing to spend at all.
    const capped = await request.put(
      `${API}/admin/users/${user.id}/assignment`,
      {
        headers: auth(token),
        data: { group_id: null, overrides: { monthly_credits: 0 } },
      },
    )
    expect(capped.ok(), await capped.text()).toBeTruthy()

    await logInUser(page, email, password)
    await page.goto("/usage")
    await expect(page.getByTestId("credit-balance")).toContainText(
      "used everything for this month",
    )

    // Refused with 402, which is the one status that means exactly this.
    const asked = await request.post(`${API}/ask/`, {
      headers: { ...auth(await tokenFor(request, email, password)) },
      data: { q: "anything" },
    })
    expect(asked.status()).toBe(402)

    // And the rest of the product still works: running out stops you
    // spending, not reading what you already have.
    await page.goto("/")
    await expect(page.getByTestId("dashboard-greeting")).toBeVisible()
  })
})

async function tokenFor(
  request: import("@playwright/test").APIRequestContext,
  email: string,
  password: string,
): Promise<string> {
  const { getToken } = await import("./utils/api.ts")
  return getToken(request, email, password)
}
