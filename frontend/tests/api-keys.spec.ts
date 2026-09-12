import { expect, test } from "@playwright/test"
import { API, adminToken, auth, uid } from "./utils/api.ts"

async function createKeyViaUi(
  page: import("@playwright/test").Page,
  name: string,
  scope: "read" | "write",
) {
  await page.getByTestId("create-api-key").click()
  const dialog = page.getByTestId("create-api-key-dialog")
  await dialog.getByTestId("api-key-name").fill(name)
  await dialog.getByTestId(`api-key-scope-${scope}`).click()
  await expect(dialog.getByTestId(`api-key-scope-${scope}`)).toHaveAttribute(
    "aria-pressed",
    "true",
  )
  await dialog.getByTestId("api-key-submit").click()
  // second step: the key is shown exactly once
  const value = dialog.getByTestId("api-key-value")
  await expect(value).toBeVisible()
  const key = await value.inputValue()
  expect(key.startsWith("kb_")).toBeTruthy()
  await expect(dialog).toContainText("You won't see this key again")
  await dialog.getByTestId("api-key-copy").click()
  await expect(dialog.getByTestId("api-key-copy")).toContainText("Copied")
  // Escape does not close the dialog while the key is displayed
  await page.keyboard.press("Escape")
  await expect(dialog).toBeVisible()
  await dialog.getByTestId("api-key-done").click()
  await expect(dialog).toBeHidden()
  return key
}

test.describe("API keys", () => {
  test("read key: create in Settings, use it, and see scope enforced", async ({
    page,
    request,
  }) => {
    await page.goto("/settings?tab=api-keys")
    const name = `Read key ${uid()}`
    const key = await createKeyViaUi(page, name, "read")

    const row = page.getByTestId("api-key-row").filter({ hasText: name })
    await expect(row).toBeVisible()
    await expect(row).toContainText(key.slice(0, 12))
    await expect(row).toContainText("read")

    // GET works
    const list = await request.get(`${API}/namespaces/`, { headers: auth(key) })
    expect(list.status()).toBe(200)
    // writes are refused
    const create = await request.post(`${API}/namespaces/`, {
      headers: auth(key),
      data: { name: `Nope ${uid()}` },
    })
    expect(create.status()).toBe(403)
    expect((await create.json()).detail).toContain("write scope")
    // account endpoints refuse API keys entirely
    const me = await request.get(`${API}/api-keys/`, { headers: auth(key) })
    expect(me.status()).toBe(403)
    const pw = await request.patch(`${API}/users/me/password`, {
      headers: auth(key),
      data: { current_password: "shanaka95", new_password: "whatever123" },
    })
    expect(pw.status()).toBe(403)

    // last used is recorded
    await page.reload()
    await expect(
      page.getByTestId("api-key-row").filter({ hasText: name }),
    ).toContainText(/ago|just now|second/i)
  })

  test("write key can create content; revoking it cuts access", async ({
    page,
    request,
  }) => {
    await page.goto("/settings?tab=api-keys")
    const name = `Write key ${uid()}`
    const key = await createKeyViaUi(page, name, "write")
    const row = page.getByTestId("api-key-row").filter({ hasText: name })
    await expect(row).toContainText("read & write")

    const create = await request.post(`${API}/namespaces/`, {
      headers: auth(key),
      data: { name: `Via key ${uid()}` },
    })
    expect(create.status()).toBe(200)
    const ns = await create.json()
    const doc = await request.post(`${API}/documents/`, {
      headers: auth(key),
      data: {
        namespace_id: ns.id,
        title: "From integration",
        content: "# Hello\n\nMade via API key",
        content_format: "markdown",
      },
    })
    expect(doc.status()).toBe(200)

    // revoke through the UI
    await row.getByTestId("api-key-revoke").click()
    await expect(page.getByRole("alertdialog")).toContainText(
      `Revoke “${name}”?`,
    )
    await page.getByTestId("api-key-revoke-confirm").click()
    await expect(page.getByText(/revoked/)).toBeVisible()
    await expect(
      page.getByTestId("api-key-row").filter({ hasText: name }),
    ).toHaveCount(0)

    const after = await request.get(`${API}/namespaces/`, {
      headers: auth(key),
    })
    expect(after.status()).toBe(403)
    expect((await after.json()).detail).toBe("Invalid API key")
  })

  test("expiry option is stored and shown in the table", async ({
    page,
    request,
  }) => {
    await page.goto("/settings?tab=api-keys")
    const name = `Expiring ${uid()}`
    await page.getByTestId("create-api-key").click()
    await page.getByTestId("api-key-name").fill(name)
    await page.getByTestId("api-key-expiry").click()
    await page.getByRole("option", { name: "30 days" }).click()
    await page.getByTestId("api-key-submit").click()
    await expect(page.getByTestId("api-key-value")).toBeVisible()
    await page.getByTestId("api-key-done").click()
    const row = page.getByTestId("api-key-row").filter({ hasText: name })
    await expect(row).toBeVisible()

    const token = await adminToken(request)
    const keys = await (
      await request.get(`${API}/api-keys/`, { headers: auth(token) })
    ).json()
    const created = keys.data.find((k: { name: string }) => k.name === name)
    expect(created.expires_at).toBeTruthy()
    const days =
      (new Date(created.expires_at).getTime() - Date.now()) / 86_400_000
    expect(days).toBeGreaterThan(29)
    expect(days).toBeLessThan(31)
  })

  test("validation: a name is required", async ({ page }) => {
    await page.goto("/settings?tab=api-keys")
    await page.getByTestId("create-api-key").click()
    await page.getByTestId("api-key-submit").click()
    await expect(page.getByText("Give the key a name")).toBeVisible()
    await page.getByRole("button", { name: "Cancel" }).click()
    await expect(page.getByTestId("create-api-key-dialog")).toBeHidden()
  })

  test("a bogus kb_ token is rejected with 403", async ({ request }) => {
    const r = await request.get(`${API}/namespaces/`, {
      headers: auth("kb_this_is_not_a_real_key"),
    })
    expect(r.status()).toBe(403)
    const missing = await request.get(`${API}/namespaces/`)
    expect(missing.status()).toBe(401)
  })
})
