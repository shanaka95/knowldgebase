import { type Browser, expect, type Page, test } from "@playwright/test"
import {
  API,
  adminToken,
  auth,
  createDocument,
  createNamespace,
  createTestUser,
  getToken,
  updateDocument,
} from "./utils/api.ts"
import { loginAs } from "./utils/ui.ts"

async function freshUserPage(
  browser: Browser,
  email: string,
  password: string,
): Promise<Page> {
  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  })
  const page = await context.newPage()
  await loginAs(page, email, password)
  return page
}

test.describe("Sharing", () => {
  test("share a page as viewer via the dialog, then upgrade to editor", async ({
    page,
    browser,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      content: "<p>Shared content</p>",
    })
    const guest = await createTestUser(request)

    // owner shares from the document menu
    await page.goto(`/s/${ns.slug}/d/${doc.id}?mode=view`)
    await page.getByTestId("document-menu").click()
    await page.getByRole("menuitem", { name: "Share" }).click()
    const dialog = page.getByTestId("share-dialog")
    await expect(dialog).toContainText(`Share “${doc.title}”`)
    await expect(dialog).toContainText("Nobody has been added yet")
    await dialog.getByTestId("share-email").fill(guest.email)
    await dialog.getByTestId("share-submit").click()
    await expect(page.getByText("Access granted")).toBeVisible()
    await expect(dialog.getByTestId("share-row")).toContainText(guest.email)
    await page.keyboard.press("Escape")

    // guest: shared list + read-only page
    const guestPage = await freshUserPage(browser, guest.email, guest.password)
    await guestPage.goto("/shared")
    await expect(guestPage.getByTestId("shared-document")).toContainText(
      doc.title,
    )
    await guestPage.getByTestId("shared-document").click()
    await expect(guestPage.getByTestId("document-page")).toHaveAttribute(
      "data-mode",
      "view",
    )
    await expect(guestPage.getByTestId("document-title")).toHaveText(doc.title)
    await expect(guestPage.getByTestId("edit-button")).toHaveCount(0)
    // the sidebar shows the space shell with only the shared page
    await expect(guestPage.getByTestId("tree-document")).toHaveCount(1)

    const guestToken = await getToken(request, guest.email, guest.password)
    const denied = await updateDocument(request, guestToken, doc.id, {
      title: "hijack",
    })
    expect(denied.status()).toBe(403)

    // owner upgrades the guest to editor
    await page.getByTestId("document-menu").click()
    await page.getByRole("menuitem", { name: "Share" }).click()
    await page
      .getByTestId("share-row")
      .filter({ hasText: guest.email })
      .getByRole("combobox", { name: "Role" })
      .click()
    await page.getByRole("option", { name: /Can edit/ }).click()
    await expect(
      page.getByTestId("share-row").getByRole("combobox", { name: "Role" }),
    ).toContainText("Can edit")
    await page.keyboard.press("Escape")

    await guestPage.reload()
    await expect(guestPage.getByTestId("edit-button")).toBeVisible()
    const allowed = await updateDocument(request, guestToken, doc.id, {
      title: "edited by guest",
    })
    expect(allowed.ok()).toBeTruthy()
    // but a shared-only editor cannot re-share
    const reshare = await request.post(`${API}/documents/${doc.id}/shares`, {
      headers: auth(guestToken),
      data: { email: "someone@example.com", role: "viewer" },
    })
    expect(reshare.status()).toBe(403)

    // owner removes access
    await page.getByTestId("document-menu").click()
    await page.getByRole("menuitem", { name: "Share" }).click()
    await page.getByRole("button", { name: `Remove ${guest.email}` }).click()
    await expect(page.getByText("Access removed")).toBeVisible()
    await guestPage.goto(`/s/${ns.slug}/d/${doc.id}?mode=view`)
    await expect(guestPage.getByTestId("not-found-state")).toBeVisible()
    await guestPage.context().close()
  })

  test("space membership grants access to every page; removal revokes it", async ({
    page,
    browser,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    const member = await createTestUser(request)

    await page.goto(`/s/${ns.slug}/settings?tab=members`)
    await page.getByTestId("member-email").fill(member.email)
    await page.getByTestId("member-role").click()
    await page.getByRole("option", { name: "Viewer" }).click()
    await page.getByTestId("member-add").click()
    await expect(page.getByText("Member added")).toBeVisible()
    const row = page.getByTestId("member-row").filter({ hasText: member.email })
    await expect(row).toBeVisible()
    await expect(row.getByRole("combobox", { name: "Role" })).toContainText(
      "Viewer",
    )

    const memberPage = await freshUserPage(
      browser,
      member.email,
      member.password,
    )
    await memberPage.getByTestId("namespace-switcher").click()
    await expect(
      memberPage.getByTestId(`namespace-option-${ns.slug}`),
    ).toBeVisible()
    await memberPage.getByTestId(`namespace-option-${ns.slug}`).click()
    await expect(memberPage.getByTestId("space-title")).toHaveText(ns.name)
    // viewers see the page but no create buttons
    await expect(memberPage.getByTestId("document-row")).toContainText(
      doc.title,
    )
    await expect(memberPage.getByTestId("new-page")).toHaveCount(0)
    await expect(memberPage.getByTestId("space-share")).toHaveCount(0)
    await memberPage.goto("/shared")
    await expect(memberPage.getByTestId("shared-list")).toContainText(ns.name)

    // promote to editor → create buttons appear
    await row.getByRole("combobox", { name: "Role" }).click()
    await page.getByRole("option", { name: "Editor" }).click()
    await memberPage.goto(`/s/${ns.slug}`)
    await expect(memberPage.getByTestId("new-page")).toBeVisible()

    // remove → space disappears
    await page.getByRole("button", { name: `Remove ${member.email}` }).click()
    await expect(page.getByText("Member removed")).toBeVisible()
    await memberPage.goto(`/s/${ns.slug}`)
    await expect(memberPage.getByTestId("not-found-state")).toBeVisible()
    await memberPage.context().close()
  })

  test("Share dialog for a space adds members with the chosen role", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const member = await createTestUser(request)
    await page.goto(`/s/${ns.slug}`)
    await page.getByTestId("space-share").click()
    const dialog = page.getByTestId("share-dialog")
    await expect(dialog).toContainText(`Share space “${ns.name}”`)
    await expect(dialog.getByTestId("share-row")).toContainText("Owner")
    await dialog.getByTestId("share-email").fill(member.email)
    await dialog.getByTestId("share-role").click()
    await page.getByRole("option", { name: "Admin" }).click()
    await dialog.getByTestId("share-submit").click()
    await expect(page.getByText("Access granted")).toBeVisible()
    const members = await (
      await request.get(`${API}/namespaces/${ns.id}/members`, {
        headers: auth(token),
      })
    ).json()
    expect(
      members.data.find(
        (m: { user: { email: string } }) => m.user.email === member.email,
      ).role,
    ).toBe("admin")
  })

  test("sharing with an unknown e-mail shows an error toast", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    await page.goto(`/s/${ns.slug}/d/${doc.id}?mode=view`)
    await page.getByTestId("document-menu").click()
    await page.getByRole("menuitem", { name: "Share" }).click()
    await page.getByTestId("share-email").fill("ghost-user@example.com")
    await page.getByTestId("share-submit").click()
    await expect(page.getByText(/not found|no user/i).first()).toBeVisible()
  })
})
