import { expect, test } from "@playwright/test"
import {
  API,
  adminToken,
  auth,
  createDocument,
  createFolder,
  createNamespace,
  uid,
} from "./utils/api.ts"
import { treeAction, treeDocument, treeFolder } from "./utils/ui.ts"

test.describe("Sidebar tree", () => {
  test("new folder at root, nested folder and page inside it", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    await page.goto(`/s/${ns.slug}`)

    // root "+" → New folder
    const rootName = `Root ${uid()}`
    await page.getByTestId("tree-root-add").click()
    await page.getByTestId("tree-root-new-folder").click()
    await page.getByTestId("new-folder-dialog-input").fill(rootName)
    await page.getByTestId("new-folder-dialog-submit").click()
    await expect(page.getByText("Folder created")).toBeVisible()
    const root = treeFolder(page, rootName)
    await expect(root).toBeVisible()

    // nested folder via the row menu
    const nestedName = `Nested ${uid()}`
    await treeAction(page, root, "new-folder")
    await page.getByTestId("new-folder-dialog-input").fill(nestedName)
    await page.getByTestId("new-folder-dialog-submit").click()
    await expect(page.getByText("Folder created")).toBeVisible()
    // expand the root folder to reveal it
    if ((await root.getAttribute("aria-expanded")) !== "true") {
      await root.getByRole("button").first().click()
    }
    const nested = treeFolder(page, nestedName)
    await expect(nested).toBeVisible()

    // new page inside the nested folder → editor opens
    await treeAction(page, nested, "new-page")
    await expect(page).toHaveURL(/\/d\/[0-9a-f-]+\?mode=edit/)
    await expect(page.getByTestId("document-page")).toHaveAttribute(
      "data-mode",
      "edit",
    )
    const documentId = page.url().match(/\/d\/([0-9a-f-]+)/)?.[1]
    const doc = await (
      await request.get(`${API}/documents/${documentId}`, {
        headers: auth(token),
      })
    ).json()
    const folders = await (
      await request.get(`${API}/namespaces/${ns.id}/tree`, {
        headers: auth(token),
      })
    ).json()
    const nestedFolder = folders.folders.find(
      (f: { name: string }) => f.name === nestedName,
    )
    expect(doc.folder_id).toBe(nestedFolder.id)
    // breadcrumb shows space › root › nested › Untitled
    const crumbs = page.getByRole("navigation", { name: "breadcrumb" })
    await expect(crumbs).toContainText(ns.name)
    await expect(crumbs).toContainText(rootName)
    await expect(crumbs).toContainText(nestedName)
  })

  test("inline rename via menu persists after reload", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      title: `Rename me ${uid()}`,
    })
    await page.goto(`/s/${ns.slug}`)
    const row = treeDocument(page, doc.title)
    await expect(row).toBeVisible()
    await treeAction(page, row, "rename")
    const input = page.getByTestId("tree-rename-input")
    await expect(input).toBeFocused()
    const newTitle = `Renamed ${uid()}`
    await input.fill(newTitle)
    await input.press("Enter")
    await expect(treeDocument(page, newTitle)).toBeVisible()
    await page.reload()
    await expect(treeDocument(page, newTitle)).toBeVisible()
    await expect(treeDocument(page, doc.title)).toHaveCount(0)
  })

  test("double-click renames a folder; Escape cancels", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const folder = await createFolder(request, token, ns.id, `Dbl ${uid()}`)
    await page.goto(`/s/${ns.slug}`)
    const row = treeFolder(page, folder.name)
    await row.getByRole("button").first().dblclick()
    const input = page.getByTestId("tree-rename-input")
    await input.fill("should not stick")
    await input.press("Escape")
    await expect(treeFolder(page, folder.name)).toBeVisible()
    await expect(page.getByTestId("tree-rename-input")).toHaveCount(0)
  })

  test("right-click shows a context menu with the node actions", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    await page.goto(`/s/${ns.slug}`)
    await treeDocument(page, doc.title).click({ button: "right" })
    const menu = page.getByRole("menu")
    await expect(menu).toBeVisible()
    for (const label of [
      "New page",
      "Open page",
      "Copy link",
      "Rename",
      "Move to…",
      "Share",
      "Delete",
    ]) {
      await expect(menu.getByRole("menuitem", { name: label })).toBeVisible()
    }
    await page.keyboard.press("Escape")
    await expect(menu).toBeHidden()
  })

  test("expand / collapse state persists across reloads", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const folder = await createFolder(request, token, ns.id, `Exp ${uid()}`)
    await createDocument(request, token, ns.id, {
      title: `Inside ${uid()}`,
      folder_id: folder.id,
    })
    await page.goto(`/s/${ns.slug}`)
    const row = treeFolder(page, folder.name)
    await expect(row).toHaveAttribute("aria-expanded", "false")
    // the chevron toggles without navigating
    await row.locator("span[aria-hidden]").first().click()
    await expect(row).toHaveAttribute("aria-expanded", "true")
    await expect(page.getByTestId("tree-document")).toHaveCount(1)
    await page.reload()
    await expect(treeFolder(page, folder.name)).toHaveAttribute(
      "aria-expanded",
      "true",
    )
    await treeFolder(page, folder.name)
      .locator("span[aria-hidden]")
      .first()
      .click()
    await expect(treeFolder(page, folder.name)).toHaveAttribute(
      "aria-expanded",
      "false",
    )
    await expect(page.getByTestId("tree-document")).toHaveCount(0)
  })

  test("move a page into a folder through the Move dialog", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const folder = await createFolder(request, token, ns.id, `Dest ${uid()}`)
    const doc = await createDocument(request, token, ns.id, {
      title: `Mover ${uid()}`,
    })
    await page.goto(`/s/${ns.slug}/d/${doc.id}?mode=view`)
    const crumbs = page.getByRole("navigation", { name: "breadcrumb" })
    await expect(crumbs).not.toContainText(folder.name)

    await page.getByTestId("document-menu").click()
    await page.getByRole("menuitem", { name: "Move to…" }).click()
    const dialog = page.getByTestId("move-dialog")
    await expect(dialog).toBeVisible()
    await expect(dialog.getByTestId("move-submit")).toBeDisabled() // unchanged
    await dialog
      .getByTestId("move-folder-option")
      .filter({ hasText: folder.name })
      .getByRole("button", { name: folder.name })
      .click()
    await dialog.getByTestId("move-submit").click()
    await expect(page.getByText("Moved")).toBeVisible()
    await expect(crumbs).toContainText(folder.name)

    const fresh = await (
      await request.get(`${API}/documents/${doc.id}`, { headers: auth(token) })
    ).json()
    expect(fresh.folder_id).toBe(folder.id)
    // and back to root
    await page.getByTestId("document-menu").click()
    await page.getByRole("menuitem", { name: "Move to…" }).click()
    await page.getByTestId("move-root-option").click()
    await page.getByTestId("move-submit").click()
    await expect(page.getByText("Moved")).toBeVisible()
    await expect(crumbs).not.toContainText(folder.name)
  })

  test("delete a folder warns about nested content and removes everything", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const folder = await createFolder(request, token, ns.id, `Del ${uid()}`)
    const child = await createFolder(request, token, ns.id, "Child", folder.id)
    const doc = await createDocument(request, token, ns.id, {
      folder_id: child.id,
    })
    await page.goto(`/s/${ns.slug}`)
    await treeAction(page, treeFolder(page, folder.name), "delete")
    const dialog = page.getByTestId("delete-dialog")
    await expect(dialog).toContainText("2 nested items")
    await dialog.getByTestId("delete-dialog-submit").click()
    await expect(page.getByText("Folder deleted")).toBeVisible()
    await expect(treeFolder(page, folder.name)).toHaveCount(0)
    const r = await request.get(`${API}/documents/${doc.id}`, {
      headers: auth(token),
    })
    expect(r.status()).toBe(404)
  })

  test("deleting the page you are viewing navigates back to the space", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    await page.goto(`/s/${ns.slug}/d/${doc.id}?mode=view`)
    await page.getByTestId("document-menu").click()
    await page.getByRole("menuitem", { name: "Delete" }).click()
    await expect(page.getByTestId("delete-dialog")).toContainText(
      "attachments and its embeddings",
    )
    await page.getByTestId("delete-dialog-submit").click()
    await expect(page.getByText("Page deleted")).toBeVisible()
    await expect(page).toHaveURL(`/s/${ns.slug}`)
    await expect(treeDocument(page, doc.title)).toHaveCount(0)
  })

  test("folder page lists contents and the New page button opens the editor", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const folder = await createFolder(request, token, ns.id, `List ${uid()}`)
    const doc = await createDocument(request, token, ns.id, {
      folder_id: folder.id,
    })
    await page.goto(`/s/${ns.slug}/f/${folder.id}`)
    await expect(page.getByTestId("folder-title")).toHaveText(folder.name)
    await expect(page.getByTestId("document-row")).toContainText(doc.title)
    // switch to grid view
    await page.getByRole("radio", { name: "Grid view" }).click()
    await expect(page.getByTestId("document-card")).toContainText(doc.title)
    await page.getByTestId("new-page").click()
    await expect(page).toHaveURL(/mode=edit/)
  })
})
