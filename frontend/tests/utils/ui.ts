import { expect, type Locator, type Page } from "@playwright/test"

export async function loginAs(page: Page, email: string, password: string) {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/")
  await expect(page.getByTestId("dashboard-greeting")).toBeVisible()
}

export function documentUrl(
  slug: string,
  documentId: string,
  mode: "view" | "edit" = "view",
  panel?: "ai" | "toc",
) {
  const search = new URLSearchParams({ mode })
  if (panel) search.set("panel", panel)
  return `/s/${slug}/d/${documentId}?${search.toString()}`
}

export async function openDocument(
  page: Page,
  slug: string,
  documentId: string,
  mode: "view" | "edit" = "view",
  panel?: "ai" | "toc",
) {
  await page.goto(documentUrl(slug, documentId, mode, panel))
  // the editor bundle is large; give the route a bit longer under load
  await expect(page.getByTestId("document-page")).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByTestId("document-page")).toHaveAttribute(
    "data-mode",
    mode,
  )
}

/** The Tiptap contenteditable surface. */
export function editorSurface(page: Page): Locator {
  return page.getByTestId("editor").locator(".ProseMirror")
}

export async function focusEditorEnd(page: Page) {
  const surface = editorSurface(page)
  await surface.click()
  await page.keyboard.press("ControlOrMeta+End")
}

/**
 * Type `/query`, wait for the slash menu to settle on the expected block and
 * confirm it with Enter.
 */
export async function slash(page: Page, query: string, expectTitle: string) {
  await page.keyboard.type(`/${query}`)
  const menu = page.getByTestId("slash-menu")
  await expect(menu).toBeVisible()
  await expect(
    menu.getByRole("option", { selected: true }).first(),
  ).toContainText(expectTitle)
  await page.keyboard.press("Enter")
  await expect(menu).toBeHidden()
}

export async function waitForSaved(page: Page, timeout = 15_000) {
  await expect(page.getByTestId("save-indicator")).toHaveAttribute(
    "data-status",
    "saved",
    { timeout },
  )
}

export async function expectToast(page: Page, text: string | RegExp) {
  await expect(page.getByText(text).first()).toBeVisible()
}

/**
 * Sidebar tree row for a page/folder by its label. Nested rows live inside
 * their parent's <li>, so match on the row's own button/link only.
 */
export function treeDocument(page: Page, title: string): Locator {
  return page.getByTestId("tree-document").filter({
    has: page.locator(":scope > div > :is(a, button)", { hasText: title }),
  })
}

export function treeFolder(page: Page, name: string): Locator {
  return page.getByTestId("tree-folder").filter({
    has: page.locator(":scope > div > :is(a, button)", { hasText: name }),
  })
}

/** Open the hover "…" menu of a tree row and click an action by key. */
export async function treeAction(page: Page, row: Locator, key: string) {
  await row.hover()
  await row.getByTestId("tree-node-actions").first().click()
  await page.getByTestId(`tree-action-${key}`).click()
}
