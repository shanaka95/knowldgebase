import { type Browser, expect, type Page, test } from "@playwright/test"
import { firstSuperuser } from "./config.ts"
import {
  adminToken,
  createDocument,
  createNamespace,
  createTestUser,
  getInvitations,
  getToken,
  shareDocumentWithMany,
  uid,
} from "./utils/api.ts"
import { invitationToken, verificationToken } from "./utils/mail.ts"
import { enterTwoFactorCode, loginAs } from "./utils/ui.ts"

/** A browser with no session at all — the state a shared link arrives in. */
async function anonymousPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  })
  return context.newPage()
}

async function openShareDialog(page: Page, slug: string, documentId: string) {
  await page.goto(`/s/${slug}/d/${documentId}?mode=view`)
  await page.getByTestId("document-menu").click()
  await page.getByRole("menuitem", { name: "Share" }).click()
  const dialog = page.getByTestId("share-dialog")
  await expect(dialog).toBeVisible()
  return dialog
}

async function addChip(page: Page, dialogTestId: string, email: string) {
  const input = page.getByTestId(dialogTestId).getByTestId("share-email")
  await input.fill(email)
  await input.press("Enter")
}

test.describe("Sharing a page with several people", () => {
  test("reports who got access, who was invited and what was skipped", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    const guest = await createTestUser(request)
    const stranger = `ghost_${uid()}@example.com`

    const dialog = await openShareDialog(page, ns.slug, doc.id)
    await addChip(page, "share-dialog", guest.email)
    await addChip(page, "share-dialog", stranger)
    // your own address is not a recipient, and the reply says so
    await addChip(page, "share-dialog", firstSuperuser)

    await expect(dialog.getByTestId("share-chip")).toHaveCount(3)
    await expect(
      dialog.getByTestId("share-chip").filter({ hasText: stranger }),
    ).toHaveAttribute("data-status", "new")
    await expect(dialog.getByTestId("share-invite-notice")).toContainText(
      "1 of these addresses doesn't have a PlusGPT account yet",
    )

    await dialog.getByTestId("share-message").fill("Have a look at page three.")
    await dialog.getByTestId("share-submit").click()

    const result = dialog.getByTestId("share-result")
    await expect(result).toContainText("1 person now has access")
    await expect(result).toContainText(guest.email)
    await expect(result).toContainText("1 invitation sent")
    await expect(dialog.getByTestId("share-skipped")).toContainText(
      "That is your own address",
    )

    // both outcomes are visible in the list afterwards, told apart
    await expect(dialog.getByTestId("share-row")).toContainText(guest.email)
    await expect(dialog.getByTestId("invitation-row")).toContainText(
      "Invited — not yet accepted",
    )
    // the counter counts an invitation as a recipient, exactly as the API does
    await expect(dialog.getByTestId("share-recipients")).toContainText(
      "2 of 50 people",
    )

    const pending = await getInvitations(request, token, doc.id)
    expect(pending.map((i: { email: string }) => i.email)).toContain(stranger)
  })

  test("a half-typed address is never looked up and blocks the submit", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)

    const lookups: string[] = []
    page.on("request", (req) => {
      const url = new URL(req.url())
      if (url.pathname.endsWith("/users/lookup")) {
        lookups.push(url.searchParams.get("email") ?? "")
      }
    })

    const dialog = await openShareDialog(page, ns.slug, doc.id)
    const input = dialog.getByTestId("share-email")
    // typing a partial address must not reach the lookup, nor become a chip
    await input.pressSequentially("colle", { delay: 30 })
    await expect(dialog.getByTestId("share-chip")).toHaveCount(0)
    await expect(dialog.getByTestId("share-submit")).toBeDisabled()

    await input.press("Enter")
    await expect(dialog.getByTestId("share-chip")).toHaveAttribute(
      "data-status",
      "invalid",
    )
    await expect(dialog.getByTestId("share-invalid")).toContainText(
      "is not a valid e-mail address",
    )
    await expect(dialog.getByTestId("share-submit")).toBeDisabled()
    expect(lookups).toEqual([])

    // Backspace takes the bad chip back for editing …
    await input.press("Backspace")
    await expect(dialog.getByTestId("share-chip")).toHaveCount(0)
    // … and a complete address can be sent without pressing Enter at all
    await input.fill("someone@example.com")
    await expect(dialog.getByTestId("share-submit")).toBeEnabled()
    await expect.poll(() => lookups).toEqual(["someone@example.com"])
  })
})

test.describe("Sharing a page by link", () => {
  test("publishes, reads without a session, and withdraws", async ({
    page,
    browser,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      content: "<p>Readable by anyone with the link</p>",
    })

    const dialog = await openShareDialog(page, ns.slug, doc.id)
    const section = dialog.getByTestId("public-link-section")
    await expect(section).toHaveAttribute("data-state", "off")
    await section.getByTestId("public-link-switch").click()
    await expect(section).toHaveAttribute("data-state", "on")
    await expect(section).toContainText(
      "Anyone with this link can read the page without signing in",
    )

    const url = await section.getByTestId("public-link-url").inputValue()
    expect(url).toContain("/p/")

    const visitor = await anonymousPage(browser)
    await visitor.goto(url)
    await expect(visitor.getByTestId("public-document-title")).toHaveText(
      doc.title,
    )
    await expect(visitor.getByTestId("public-document")).toContainText(
      "Readable by anyone with the link",
    )
    await expect(visitor.getByTestId("public-document-sharer")).toContainText(
      "Shared by",
    )
    // no session was needed, and none was created
    expect(
      await visitor.evaluate(() => localStorage.getItem("access_token")),
    ).toBeNull()

    await section.getByTestId("public-link-switch").click()
    await expect(section).toHaveAttribute("data-state", "off")
    await visitor.reload()
    await expect(visitor.getByTestId("public-document-missing")).toContainText(
      "No page is shared at this link",
    )
    await visitor.context().close()
  })
})

test.describe("The invitation landing page", () => {
  test("explains who shared what and prefills the sign-up address", async ({
    browser,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    const stranger = `ghost_${uid()}@example.com`

    const shared = await shareDocumentWithMany(request, token, doc.id, {
      emails: [stranger],
      role: "viewer",
    })
    expect(shared.ok(), await shared.text()).toBeTruthy()

    const inviteToken = await invitationToken(request, stranger)
    const visitor = await anonymousPage(browser)
    await visitor.goto(`/invite?token=${inviteToken}`)

    await expect(visitor.getByTestId("invite-landing")).toContainText(
      `shared “${doc.title}” with you`,
    )
    await expect(visitor.getByTestId("invite-landing")).toContainText(stranger)

    await visitor.getByTestId("invite-create-account").click()
    await visitor.waitForURL(/\/signup\?/)
    await expect(visitor.getByTestId("email-input")).toHaveValue(stranger)
    await visitor.context().close()
  })

  test("sign-up from the invitation ends on the page that was shared", async ({
    browser,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      title: `Invited ${uid()}`,
      content: "<p>Waiting for you</p>",
    })
    const stranger = `ghost_${uid()}@example.com`
    const password = `pw_${uid()}${uid()}`

    const shared = await shareDocumentWithMany(request, token, doc.id, {
      emails: [stranger],
      role: "viewer",
    })
    expect(shared.ok(), await shared.text()).toBeTruthy()

    // One tab throughout: the page the invitation named is remembered in
    // session storage, which is exactly as long as this journey lasts.
    const visitor = await anonymousPage(browser)
    await visitor.goto(
      `/invite?token=${await invitationToken(request, stranger)}`,
    )
    await visitor.getByTestId("invite-create-account").click()

    await visitor.getByTestId("full-name-input").fill("Invited Person")
    await visitor.getByTestId("password-input").fill(password)
    await visitor.getByTestId("confirm-password-input").fill(password)
    await visitor.getByRole("button", { name: "Sign Up" }).click()
    await expect(visitor.getByTestId("check-your-inbox")).toBeVisible()

    // Confirming the address is what turns the invitation into access.
    await visitor.goto(
      `/verify-email?token=${await verificationToken(request, stranger)}`,
    )
    await expect(visitor.getByTestId("verify-email-success")).toBeVisible()

    await visitor.goto("/login")
    await visitor.getByTestId("email-input").fill(stranger)
    await visitor.getByTestId("password-input").fill(password)
    await visitor.getByRole("button", { name: "Log In" }).click()
    await enterTwoFactorCode(visitor, stranger)

    await visitor.waitForURL(new RegExp(`/d/${doc.id}`))
    await expect(visitor.getByTestId("document-title")).toHaveText(doc.title)
    await visitor.context().close()
  })

  test("a token that is not valid explains itself in the backend's words", async ({
    browser,
  }) => {
    const visitor = await anonymousPage(browser)
    await visitor.goto(`/invite?token=not-a-real-token-${uid()}`)
    await expect(visitor.getByTestId("invite-failed")).toContainText(
      "This invitation is not valid",
    )
    await visitor.context().close()
  })
})

test.describe("Making a copy", () => {
  test("copies a page from the document menu into a chosen space", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      title: `Original ${uid()}`,
      content: "<p>Worth keeping</p>",
    })

    await page.goto(`/s/${ns.slug}/d/${doc.id}?mode=view`)
    await page.getByTestId("document-menu").click()
    await page.getByTestId("document-make-a-copy").click()

    const dialog = page.getByTestId("copy-dialog")
    await expect(dialog.getByTestId("copy-title")).toHaveValue(
      `${doc.title} (copy)`,
    )
    await dialog.getByTestId("copy-submit").click()

    await expect(
      page.getByText("It is private until you share it"),
    ).toBeVisible()
    await expect(page.getByTestId("document-title")).toHaveText(
      `${doc.title} (copy)`,
    )
    // a separate page, not the one that was copied
    expect(page.url()).not.toContain(doc.id)
  })

  test("keeps a copy of a page somebody shared with me", async ({
    browser,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      title: `Borrowed ${uid()}`,
      content: "<p>Someone else's page</p>",
    })
    const guest = await createTestUser(request)
    const guestToken = await getToken(request, guest.email, guest.password)
    const ownSpace = await createNamespace(request, guestToken, {
      name: `Mine ${uid()}`,
    })

    const shared = await shareDocumentWithMany(request, token, doc.id, {
      emails: [guest.email],
      role: "viewer",
    })
    expect(shared.ok(), await shared.text()).toBeTruthy()

    const context = await browser.newContext({
      storageState: { cookies: [], origins: [] },
    })
    const guestPage = await context.newPage()
    await loginAs(guestPage, guest.email, guest.password)

    await guestPage.goto("/shared")
    await guestPage
      .getByRole("button", { name: `Make a copy of ${doc.title}` })
      .click()

    const dialog = guestPage.getByTestId("copy-dialog")
    // the original's space is not writable for them, so the copy lands in theirs
    await expect(dialog.getByTestId("destination-space-select")).toContainText(
      ownSpace.name,
    )
    await dialog.getByTestId("copy-submit").click()

    await expect(
      guestPage.getByText("It is private until you share it"),
    ).toBeVisible()
    await expect(guestPage.getByTestId("document-title")).toHaveText(
      `${doc.title} (copy)`,
    )
    await expect(guestPage.getByTestId("editor")).toContainText(
      "Someone else's page",
    )
    await context.close()
  })
})
