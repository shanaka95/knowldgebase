import {
  type Browser,
  expect,
  type Locator,
  type Page,
  test,
} from "@playwright/test"
import { firstSuperuser } from "./config.ts"
import {
  addMember,
  adminToken,
  createDocument,
  createNamespace,
  createTestUser,
  getMembers,
  getNamespaceInvitations,
  shareDocumentWithMany,
  shareNamespaceWithMany,
  uid,
} from "./utils/api.ts"
import { invitationToken } from "./utils/mail.ts"
import { loginAs } from "./utils/ui.ts"

/** A browser with no session at all — the state an invitation link arrives in. */
async function anonymousPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  })
  return context.newPage()
}

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

async function openSpaceShareDialog(page: Page, slug: string) {
  await page.goto(`/s/${slug}`)
  await page.getByTestId("space-share").click()
  const dialog = page.getByTestId("share-dialog")
  await expect(dialog).toBeVisible()
  return dialog
}

async function addChip(dialog: Locator, email: string) {
  const input = dialog.getByTestId("share-email")
  await input.fill(email)
  await input.press("Enter")
}

/**
 * A chip by address. Not by text: once the lookup lands, a chip for somebody
 * with an account shows their name instead of the address they were typed as.
 */
function chip(dialog: Locator, email: string): Locator {
  return dialog.locator(`[data-testid="share-chip"][title="${email}"]`)
}

test.describe("Sharing a space with several people", () => {
  test("reports who joined, who was invited and what was skipped", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const guest = await createTestUser(request)
    const stranger = `ghost_${uid()}@example.com`

    const dialog = await openSpaceShareDialog(page, ns.slug)
    await expect(dialog).toContainText(`Share space “${ns.name}”`)
    // the grant a space share makes is stated before anything is sent
    await expect(dialog).toContainText("including ones added later")
    await expect(dialog.getByTestId("share-row")).toContainText("Owner")

    await addChip(dialog, guest.email)
    await addChip(dialog, stranger)
    // your own address is not a recipient, and the reply says so
    await addChip(dialog, firstSuperuser)

    await expect(dialog.getByTestId("share-chip")).toHaveCount(3)
    await expect(chip(dialog, guest.email)).toHaveAttribute(
      "data-status",
      "known",
    )
    await expect(chip(dialog, stranger)).toHaveAttribute("data-status", "new")
    await expect(dialog.getByTestId("share-invite-notice")).toContainText(
      "1 of these addresses doesn't have a PlusGPT account yet",
    )
    await expect(dialog.getByTestId("share-invite-notice")).toContainText(
      "the space opens as soon as they confirm it",
    )

    await dialog.getByTestId("share-role").click()
    await page.getByRole("option", { name: "Editor" }).click()
    await dialog.getByTestId("share-message").fill("Notes for the new quarter")
    await dialog.getByTestId("share-submit").click()

    const result = dialog.getByTestId("share-result")
    await expect(result).toContainText("1 person now has access")
    await expect(result).toContainText(guest.email)
    await expect(result).toContainText("1 invitation sent")
    await expect(result).toContainText("The space opens for them")
    // the reason for a skipped address is the backend's, verbatim
    await expect(dialog.getByTestId("share-skipped")).toContainText(
      "That is your own address",
    )

    await expect(
      dialog.getByTestId("share-row").filter({ hasText: guest.email }),
    ).toBeVisible()
    const invitation = dialog
      .getByTestId("invitation-row")
      .filter({ hasText: stranger })
    await expect(invitation).toContainText("Invited, not yet accepted")
    // owner + new member + pending invitation
    await expect(dialog.getByTestId("share-recipients")).toContainText("3 of")

    const members = await getMembers(request, token, ns.id)
    expect(
      members.data.find(
        (m: { user: { email: string } }) => m.user.email === guest.email,
      ).role,
    ).toBe("editor")
    expect(await getNamespaceInvitations(request, token, ns.id)).toHaveLength(1)

    await dialog
      .getByRole("button", {
        name: `Withdraw the invitation for ${stranger}`,
      })
      .click()
    await expect(page.getByText("Invitation withdrawn")).toBeVisible()
    await expect(dialog.getByTestId("invitation-row")).toHaveCount(0)
    expect(await getNamespaceInvitations(request, token, ns.id)).toHaveLength(0)
  })

  test("only a space admin gets the sharing controls", async ({
    page,
    browser,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const member = await createTestUser(request)
    await addMember(request, token, ns.id, member.email, "viewer")

    const memberPage = await freshUserPage(
      browser,
      member.email,
      member.password,
    )
    await memberPage.goto(`/s/${ns.slug}`)
    await expect(memberPage.getByTestId("space-title")).toHaveText(ns.name)
    await expect(memberPage.getByTestId("space-share")).toHaveCount(0)

    // promoted to admin, the same person gets the whole composer
    const dialog = await openSpaceShareDialog(page, ns.slug)
    await dialog
      .getByTestId("share-row")
      .filter({ hasText: member.email })
      .getByRole("combobox", { name: "Role" })
      .click()
    await page.getByRole("option", { name: /Admin/ }).click()
    await page.keyboard.press("Escape")

    await memberPage.reload()
    const memberDialog = await openSpaceShareDialog(memberPage, ns.slug)
    await expect(memberDialog.getByTestId("share-email")).toBeVisible()
    await expect(memberDialog.getByTestId("share-submit")).toBeVisible()
    await memberPage.context().close()
  })

  test("an invitation to a space says what the space opens", async ({
    browser,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const stranger = `ghost_${uid()}@example.com`
    const shared = await shareNamespaceWithMany(request, token, ns.id, {
      emails: [stranger],
      role: "editor",
    })
    expect(shared.ok(), await shared.text()).toBeTruthy()

    const inviteToken = await invitationToken(request, stranger)
    const visitor = await anonymousPage(browser)
    await visitor.goto(`/invite?token=${inviteToken}`)

    const landing = visitor.getByTestId("invite-landing")
    // the landing page names the space, not a page, and says how far it reaches
    await expect(landing).toContainText(
      `shared the space “${ns.name}” with you`,
    )
    await expect(landing).toContainText(
      "the space opens as soon as you confirm",
    )
    await expect(landing).toContainText("create and edit pages anywhere in it")
    await expect(landing).toContainText("including ones added later")
    await visitor.context().close()
  })
})

test.describe("A space that belongs to someone else", () => {
  test("is marked as shared wherever it is named", async ({
    browser,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    await createDocument(request, token, ns.id)
    const guest = await createTestUser(request)
    const shared = await shareNamespaceWithMany(request, token, ns.id, {
      emails: [guest.email],
      role: "viewer",
    })
    expect(shared.ok(), await shared.text()).toBeTruthy()

    const guestPage = await freshUserPage(browser, guest.email, guest.password)

    // the dashboard card
    const card = guestPage
      .getByTestId("namespace-cards")
      .getByRole("link", { name: new RegExp(ns.name) })
    await expect(card.getByTestId("shared-space-badge")).toBeVisible()

    // the sidebar switcher — still selectable, and marked
    await guestPage.getByTestId("namespace-switcher").click()
    const option = guestPage.getByTestId(`namespace-option-${ns.slug}`)
    await expect(option.getByTestId("shared-space-badge")).toBeVisible()
    await option.click()

    // the space header says whose space it is
    const header = guestPage.getByTestId("space-header")
    await expect(guestPage.getByTestId("space-title")).toHaveText(ns.name)
    await expect(header.getByTestId("shared-space-badge")).toContainText(
      "Shared with you",
    )
    await expect(header.getByTestId("space-owner")).toContainText("Owned by")
    await guestPage.context().close()
  })

  test("a whole space and a single page are told apart on /shared", async ({
    browser,
    request,
  }) => {
    const token = await adminToken(request)
    const whole = await createNamespace(request, token)
    const other = await createNamespace(request, token)
    const doc = await createDocument(request, token, other.id)
    // a second page nobody shared, to prove the space around the shared one
    // really does stay out of reach
    await createDocument(request, token, other.id)
    const guest = await createTestUser(request)

    const spaceShare = await shareNamespaceWithMany(request, token, whole.id, {
      emails: [guest.email],
      role: "viewer",
    })
    expect(spaceShare.ok(), await spaceShare.text()).toBeTruthy()
    const pageShare = await shareDocumentWithMany(request, token, doc.id, {
      emails: [guest.email],
      role: "viewer",
    })
    expect(pageShare.ok(), await pageShare.text()).toBeTruthy()

    const guestPage = await freshUserPage(browser, guest.email, guest.password)
    await guestPage.goto("/shared")

    const spaces = guestPage.getByTestId("shared-spaces")
    await expect(spaces).toContainText("Whole spaces shared with you (1)")
    await expect(spaces).toContainText("anything added to them later")
    await expect(spaces.getByTestId("shared-space")).toContainText(whole.name)
    // the space the single page lives in is not one of them
    await expect(spaces).not.toContainText(other.name)

    const pages = guestPage.getByTestId("shared-pages")
    await expect(pages).toContainText("Individual pages shared with you (1)")
    await expect(pages.getByTestId("shared-document")).toContainText(doc.title)
    // the page names its space without implying access to it
    const origin = pages.getByTestId("shared-page-space")
    await expect(origin).toContainText(`from ${other.name}`)
    await origin.hover()
    await expect(
      guestPage.getByText(new RegExp(`rest of ${other.name}`)).first(),
    ).toBeVisible()

    // and the claim is true: the space is not one of the guest's spaces, and
    // inside it only the one shared page exists for them
    await guestPage.getByTestId("namespace-switcher").click()
    await expect(
      guestPage.getByTestId(`namespace-option-${whole.slug}`),
    ).toBeVisible()
    await expect(
      guestPage.getByTestId(`namespace-option-${other.slug}`),
    ).toHaveCount(0)
    await guestPage.keyboard.press("Escape")
    await guestPage.goto(`/s/${other.slug}`)
    await expect(guestPage.getByTestId("tree-document")).toHaveCount(1)
    await guestPage.context().close()
  })
})
