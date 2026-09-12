import { expect, test } from "@playwright/test"
import {
  API,
  adminToken,
  auth,
  createDocument,
  createNamespace,
  getDocument,
  uid,
  updateDocument,
} from "./utils/api.ts"
import {
  editorSurface,
  focusEditorEnd,
  openDocument,
  slash,
  waitForSaved,
} from "./utils/ui.ts"

test.describe("Document editor", () => {
  test("rich content round-trips through save, reload and the sanitiser", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      title: "Untitled",
      content: "",
    })
    await openDocument(page, ns.slug, doc.id, "edit")

    const title = `Editor ${uid()}`
    await page.getByTestId("document-title-input").fill(title)

    await focusEditorEnd(page)
    await page.keyboard.type("Intro paragraph about the page.")
    await page.keyboard.press("Enter")
    await slash(page, "h2", "Heading 2")
    await page.keyboard.type("First heading")
    await page.keyboard.press("Enter")
    await page.keyboard.type("Some body text under the first heading.")
    await page.keyboard.press("Enter")
    await slash(page, "bullet", "Bullet list")
    await page.keyboard.type("alpha")
    await page.keyboard.press("Enter")
    await page.keyboard.type("beta")
    await page.keyboard.press("Enter")
    await page.keyboard.press("Enter") // leave the list
    await slash(page, "h2", "Heading 2")
    await page.keyboard.type("Second heading")
    await page.keyboard.press("Enter")
    await slash(page, "code", "Code block")
    await page.keyboard.type("print('hi')")
    await page.keyboard.press("Enter")
    await page.keyboard.press("Enter")
    await page.keyboard.press("Enter") // triple enter exits the code block
    await slash(page, "info", "Info panel")
    await page.keyboard.type("Remember to hydrate.")
    await page.keyboard.press("ControlOrMeta+End")
    await page.keyboard.press("ArrowDown") // trailing paragraph after the panel
    await slash(page, "table", "Table")

    const surface = editorSurface(page)
    await expect(surface.locator("h2")).toHaveCount(2)
    await expect(surface.locator("ul li")).toHaveCount(2)
    await expect(surface.locator("pre")).toHaveCount(1)
    await expect(surface.locator('div[data-panel-type="info"]')).toHaveCount(1)
    await expect(surface.locator("table")).toHaveCount(1)
    await waitForSaved(page)

    // table of contents lists both headings
    await expect(page.getByTestId("toc")).toContainText("First heading")
    await expect(page.getByTestId("toc")).toContainText("Second heading")

    // word count is shown in the toolbar
    await expect(page.getByTestId("editor-toolbar")).toContainText(/\d+ words/)

    // reload in view mode: everything survived the server round-trip
    await openDocument(page, ns.slug, doc.id, "view")
    await expect(page.getByTestId("document-title")).toHaveText(title)
    const view = editorSurface(page)
    await expect(view).toContainText("Intro paragraph about the page.")
    await expect(view.locator("h2")).toHaveCount(2)
    await expect(view.locator("ul li")).toHaveCount(2)
    await expect(view.locator("pre")).toContainText("print('hi')")
    await expect(view.locator('div[data-panel-type="info"]')).toContainText(
      "Remember to hydrate.",
    )
    await expect(view.locator("table")).toHaveCount(1)
    await expect(page.getByTestId("editor-toolbar")).toHaveCount(0)
    await expect(view).toHaveAttribute("contenteditable", "false")

    const saved = await getDocument(request, token, doc.id)
    expect(saved.title).toBe(title)
    expect(saved.content_html).toContain('data-panel-type="info"')
    expect(saved.content_html).toContain("<table")
    expect(saved.content_html).toContain("<pre")
    expect(saved.content_text).toContain("Remember to hydrate.")
    expect(saved.version).toBeGreaterThan(1)
  })

  test("Done switches to view mode and `e` re-enters edit mode", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    await openDocument(page, ns.slug, doc.id, "edit")
    await expect(page.getByTestId("editor-toolbar")).toBeVisible()
    await page.getByTestId("done-button").click()
    await expect(page.getByTestId("document-page")).toHaveAttribute(
      "data-mode",
      "view",
    )
    await expect(page.getByTestId("editor-toolbar")).toHaveCount(0)
    await expect(page.getByTestId("edit-button")).toBeVisible()
    await page.locator("body").click()
    await page.keyboard.press("e")
    await expect(page.getByTestId("document-page")).toHaveAttribute(
      "data-mode",
      "edit",
    )
    await expect(page.getByTestId("editor-toolbar")).toBeVisible()
    await expect(page).toHaveURL(/mode=edit/)
    // Escape (outside the editor surface) goes back to view when nothing is unsaved
    await page.getByTestId("document-meta").click()
    await page.keyboard.press("Escape")
    await expect(page.getByTestId("document-page")).toHaveAttribute(
      "data-mode",
      "view",
    )
  })

  test("bubble menu appears on selection and bold is persisted", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      content: "<p>Make me bold please</p>",
    })
    await openDocument(page, ns.slug, doc.id, "edit")
    const paragraph = editorSurface(page).locator("p").first()
    await paragraph.click({ clickCount: 3 })
    const bold = page.getByRole("button", { name: "Bold" }).last()
    await expect(bold).toBeVisible()
    await bold.click()
    await expect(editorSurface(page).locator("strong")).toContainText(
      "Make me bold",
    )
    await waitForSaved(page)
    const saved = await getDocument(request, token, doc.id)
    expect(saved.content_html).toMatch(/<strong>Make me bold please<\/strong>/)
    // formatting-only change keeps the plain text → no new version
    expect(saved.version).toBe(1)
  })

  test("link insertion via the toolbar prompt", async ({ page, request }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      content: "<p>Visit the docs</p>",
    })
    await openDocument(page, ns.slug, doc.id, "edit")
    await editorSurface(page).locator("p").first().click({ clickCount: 3 })
    page.once("dialog", (d) => d.accept("https://example.com/docs"))
    await page
      .getByTestId("editor-toolbar")
      .getByRole("button", { name: "Link" })
      .click()
    const link = editorSurface(page).locator(
      "a[href='https://example.com/docs']",
    )
    await expect(link).toBeVisible()
    await waitForSaved(page)
    const saved = await getDocument(request, token, doc.id)
    expect(saved.content_html).toContain('href="https://example.com/docs"')
    expect(saved.content_html).toContain('rel="noopener noreferrer"')
  })

  test("title edits are saved and shown in the tree and breadcrumb", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    await openDocument(page, ns.slug, doc.id, "edit")
    const title = `Title ${uid()}`
    await page.getByTestId("document-title-input").fill(title)
    await waitForSaved(page)
    await expect(
      page.getByTestId("tree-document").filter({ hasText: title }),
    ).toBeVisible()
    await expect(
      page.getByRole("navigation", { name: "breadcrumb" }),
    ).toContainText(title)
    const saved = await getDocument(request, token, doc.id)
    expect(saved.title).toBe(title)
    expect(saved.version).toBe(2)
  })

  test("conflict banner when someone else saved first; Overwrite wins", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      content: "<p>original</p>",
    })
    await openDocument(page, ns.slug, doc.id, "edit")

    // hold the browser's autosave PUT until the API has bumped the version
    let intercepted = false
    await page.route(`**/api/v1/documents/${doc.id}`, async (route) => {
      if (route.request().method() === "PUT" && !intercepted) {
        intercepted = true
        const r = await updateDocument(request, token, doc.id, {
          content: "<p>changed elsewhere</p>",
          content_format: "html",
        })
        expect(r.ok()).toBeTruthy()
      }
      await route.continue()
    })

    await focusEditorEnd(page)
    await page.keyboard.type(" plus my edit")
    const banner = page.getByTestId("conflict-banner")
    await expect(banner).toBeVisible({ timeout: 15_000 })
    await expect(banner).toContainText("Server has version 2")
    await expect(page.getByTestId("save-indicator")).toHaveAttribute(
      "data-status",
      "conflict",
    )

    await banner.getByRole("button", { name: "Overwrite" }).click()
    await expect(banner).toBeHidden()
    await waitForSaved(page)
    const saved = await getDocument(request, token, doc.id)
    expect(saved.content_text).toContain("plus my edit")
    expect(saved.version).toBe(3)
  })

  test("conflict banner: Reload latest discards local edits", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      content: "<p>original</p>",
    })
    await openDocument(page, ns.slug, doc.id, "edit")
    let intercepted = false
    await page.route(`**/api/v1/documents/${doc.id}`, async (route) => {
      if (route.request().method() === "PUT" && !intercepted) {
        intercepted = true
        await updateDocument(request, token, doc.id, {
          content: "<p>server wins</p>",
          content_format: "html",
        })
      }
      await route.continue()
    })
    await focusEditorEnd(page)
    await page.keyboard.type(" local")
    const banner = page.getByTestId("conflict-banner")
    await expect(banner).toBeVisible({ timeout: 15_000 })
    await banner.getByRole("button", { name: "Reload latest" }).click()
    await expect(banner).toBeHidden()
    await expect(editorSurface(page)).toContainText("server wins")
    await expect(editorSurface(page)).not.toContainText("local")
    const saved = await getDocument(request, token, doc.id)
    expect(saved.content_text).toBe("server wins")
  })

  test("view mode shows a New version chip when the page changes remotely", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      content: "<p>v1 text</p>",
    })
    await page.clock.install()
    await openDocument(page, ns.slug, doc.id, "view")
    await expect(editorSurface(page)).toContainText("v1 text")

    await updateDocument(request, token, doc.id, {
      content: "<p>v2 text from the API</p>",
      content_format: "html",
    })
    // the poll runs every 30 s
    await page.clock.runFor(31_000)
    const chip = page.getByTestId("new-version-chip")
    await expect(chip).toBeVisible({ timeout: 10_000 })
    await expect(chip).toContainText("v2")
    await chip.click()
    await expect(editorSurface(page)).toContainText("v2 text from the API")
    await expect(chip).toBeHidden()
  })

  test("viewer without edit rights gets a read-only page", async ({
    browser,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    const { createTestUser, shareDocument } = await import("./utils/api.ts")
    const viewer = await createTestUser(request)
    await shareDocument(request, token, doc.id, viewer.email, "viewer")

    const context = await browser.newContext({
      storageState: { cookies: [], origins: [] },
    })
    const page = await context.newPage()
    const { loginAs } = await import("./utils/ui.ts")
    await loginAs(page, viewer.email, viewer.password)
    // even asking for edit mode falls back to view
    await page.goto(`/s/${ns.slug}/d/${doc.id}?mode=edit`)
    await expect(page.getByTestId("document-page")).toHaveAttribute(
      "data-mode",
      "view",
    )
    await expect(page.getByTestId("edit-button")).toHaveCount(0)
    await expect(page.getByTestId("editor-toolbar")).toHaveCount(0)
    await context.close()
  })

  test("API-visible document metadata matches the header", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    await openDocument(page, ns.slug, doc.id, "view")
    await expect(page.getByTestId("document-meta")).toContainText("v1")
    await expect(page.getByTestId("document-meta")).toContainText("Updated by")
    const r = await request.get(`${API}/documents/${doc.id}`, {
      headers: auth(token),
    })
    const fresh = await r.json()
    expect(fresh.version).toBe(1)
    expect(fresh.my_role).toBe("editor")
  })
})
