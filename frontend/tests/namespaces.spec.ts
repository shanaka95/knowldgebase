import { expect, test } from "@playwright/test"
import { API, adminToken, auth, createNamespace, uid } from "./utils/api.ts"

test.describe("Spaces (namespaces)", () => {
  test("create a space from the sidebar switcher", async ({ page }) => {
    const name = `Switcher ${uid()}`
    await page.goto("/")
    await page.getByTestId("namespace-switcher").click()
    await page.getByTestId("create-namespace").click()

    const dialog = page.getByTestId("namespace-dialog")
    await expect(dialog).toBeVisible()
    await dialog.getByTestId("namespace-name").fill(name)
    await dialog.getByPlaceholder("What lives in this space?").fill("E2E space")
    await dialog.getByRole("button", { name: "rocket" }).click()
    await dialog.getByRole("button", { name: "emerald" }).click()
    await dialog.getByTestId("namespace-submit").click()

    await expect(page.getByText("Space created")).toBeVisible()
    // navigates to the new space
    await expect(page).toHaveURL(/\/s\/switcher-/)
    await expect(page.getByTestId("space-title")).toHaveText(name)
    await expect(page.getByText("E2E space")).toBeVisible()
    // the switcher now shows it as the active space
    await expect(page.getByTestId("namespace-switcher")).toContainText(name)
  })

  test("create a space from Quick create on the dashboard", async ({
    page,
  }) => {
    const name = `Quick ${uid()}`
    await page.goto("/")
    // the dev-only router devtools button can overlap the dropdown
    await page.addStyleTag({ content: ".TanStackRouterDevtools{display:none}" })
    await page.getByTestId("quick-new-page").click()
    await page.getByRole("menuitem", { name: "New space…" }).click()
    await page.getByTestId("namespace-name").fill(name)
    await page.getByTestId("namespace-submit").click()
    await expect(page.getByText("Space created")).toBeVisible()
    await expect(page.getByTestId("space-title")).toHaveText(name)

    // dashboard cards list it
    await page.goto("/")
    await expect(page.getByTestId("namespace-cards")).toContainText(name)
  })

  test("empty name is rejected", async ({ page }) => {
    await page.goto("/")
    await page.getByTestId("namespace-switcher").click()
    await page.getByTestId("create-namespace").click()
    await page.getByTestId("namespace-name").fill("   ")
    await page.getByTestId("namespace-submit").click()
    await expect(page.getByText("Name is required")).toBeVisible()
    await expect(page.getByTestId("namespace-dialog")).toBeVisible()
  })

  test("duplicate name for the same owner is rejected", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    await page.goto("/")
    await page.getByTestId("namespace-switcher").click()
    await page.getByTestId("create-namespace").click()
    await page.getByTestId("namespace-name").fill(ns.name)
    await page.getByTestId("namespace-submit").click()
    await expect(page.getByText(/already/i).first()).toBeVisible()
  })

  test("slug route renders the space header and role badge", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token, {
      description: "Header check",
    })
    await page.goto(`/s/${ns.slug}`)
    await expect(page.getByTestId("space-title")).toHaveText(ns.name)
    await expect(page.getByText("Header check")).toBeVisible()
    await expect(page.getByText("0 pages")).toBeVisible()
    await expect(page.getByTestId("space-share")).toBeVisible()
  })

  test("edit name and description in space settings", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const newName = `Renamed ${uid()}`
    await page.goto(`/s/${ns.slug}/settings?tab=general`)
    await page.getByTestId("space-settings-name").fill(newName)
    await page.getByLabel("Description").fill("Updated description")
    await page.getByTestId("space-settings-save").click()
    await expect(page.getByText("Space updated")).toBeVisible()

    // slug changed with the name → URL follows
    await expect(page).toHaveURL(/\/s\/renamed-/)
    const r = await request.get(`${API}/namespaces/${ns.id}`, {
      headers: auth(token),
    })
    const updated = await r.json()
    expect(updated.name).toBe(newName)
    expect(updated.description).toBe("Updated description")
  })

  test("save button stays disabled until the form is dirty", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    await page.goto(`/s/${ns.slug}/settings?tab=general`)
    await expect(page.getByTestId("space-settings-save")).toBeDisabled()
    await page.getByTestId("space-settings-name").fill(`${ns.name} x`)
    await expect(page.getByTestId("space-settings-save")).toBeEnabled()
  })

  test("delete a space with type-to-confirm", async ({ page, request }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    await page.goto(`/s/${ns.slug}/settings?tab=danger`)
    await page.getByTestId("space-delete").click()

    const dialog = page.getByTestId("delete-namespace-dialog")
    await expect(dialog).toBeVisible()
    await expect(dialog.getByTestId("delete-namespace-submit")).toBeDisabled()
    await dialog.getByTestId("delete-namespace-confirm").fill("wrong name")
    await expect(dialog.getByTestId("delete-namespace-submit")).toBeDisabled()
    await dialog.getByTestId("delete-namespace-confirm").fill(ns.name)
    await dialog.getByTestId("delete-namespace-submit").click()

    await expect(page.getByText(/deleted/)).toBeVisible()
    await expect(page).toHaveURL("/")
    const r = await request.get(`${API}/namespaces/${ns.id}`, {
      headers: auth(token),
    })
    expect(r.status()).toBe(404)
    await page.goto(`/s/${ns.slug}`)
    await expect(page.getByTestId("not-found-state")).toBeVisible()
  })

  test("switcher lists spaces and switching navigates", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const a = await createNamespace(request, token)
    const b = await createNamespace(request, token)
    await page.goto(`/s/${a.slug}`)
    await page.getByTestId("namespace-switcher").click()
    await expect(page.getByTestId(`namespace-option-${a.slug}`)).toBeVisible()
    await page.getByTestId(`namespace-option-${b.slug}`).click()
    await expect(page).toHaveURL(`/s/${b.slug}`)
    await expect(page.getByTestId("space-title")).toHaveText(b.name)
  })

  test("last visited space is remembered on the dashboard", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    await page.goto(`/s/${ns.slug}`)
    await expect(page.getByTestId("space-title")).toHaveText(ns.name)
    await page.goto("/")
    await expect(page.getByTestId("namespace-switcher")).toContainText(ns.name)
  })
})
