import { expect, test } from "@playwright/test"

import {
  API,
  adminToken,
  auth,
  createDocument,
  createNamespace,
  uid,
  updateDocument,
} from "./utils/api.ts"
import { openDocument } from "./utils/ui.ts"

/**
 * A page's history, its language, and the files it came from.
 *
 * These three share a header row and a rule: reading an older version or a
 * translation is reading, never editing.
 */

test.setTimeout(120_000)

async function seed(request: Parameters<typeof adminToken>[0]) {
  const token = await adminToken(request)
  const namespace = await createNamespace(request, token, {
    name: `Versions ${uid()}`,
  })
  const document = await createDocument(request, token, namespace.id, {
    title: `Connecting to the VPN ${uid()}`,
    content:
      "<h2>Errors</h2><p>Error 407 means your VPN token has expired. " +
      "Request a new one from the IT portal.</p>",
  })
  return { token, namespace, document }
}

test("a page starts at version 1 and gains one per edit", async ({
  page,
  request,
}) => {
  const { token, namespace, document } = await seed(request)

  await openDocument(page, namespace.slug, document.id)
  await expect(page.getByTestId("version-picker")).toContainText("Version 1")

  // A change to the words is a version; the API is the honest way to make one.
  const edited = await updateDocument(request, token, document.id, {
    content:
      "<h2>Errors</h2><p>Error 407 means the token expired. Renew it.</p>",
    content_format: "html",
  })
  expect(edited.ok(), await edited.text()).toBeTruthy()

  await page.reload()
  await expect(page.getByTestId("version-picker")).toContainText("Version 2")

  await page.getByTestId("version-picker").click()
  await expect(page.getByTestId("version-option")).toHaveCount(2)
})

test("an older version can be read, and cannot be edited", async ({
  page,
  request,
}) => {
  const { token, namespace, document } = await seed(request)
  await updateDocument(request, token, document.id, {
    content: "<p>The second version of this page.</p>",
    content_format: "html",
  })

  await openDocument(page, namespace.slug, document.id)
  await page.getByTestId("version-picker").click()
  // Newest first, so the second entry is version 1.
  await page.getByTestId("version-option").nth(1).click()

  await expect(page.getByTestId("document-read-only")).toBeVisible()
  await expect(page.getByTestId("read-only-body")).toContainText("Error 407")
  await expect(page.getByTestId("edit-button")).toBeHidden()
  expect(page.url()).toContain("v=1")

  await page.getByTestId("read-only-back").click()
  await expect(page.getByTestId("document-read-only")).toBeHidden()
  await expect(page.getByTestId("edit-button")).toBeVisible()
})

test("a page can be read in another language, and the translation is kept", async ({
  page,
  request,
}) => {
  const { namespace, document } = await seed(request)
  await openDocument(page, namespace.slug, document.id)

  // Opens on the language the page is written in, which nobody had to declare.
  await expect(page.getByTestId("language-picker")).toContainText("English")

  await page.getByTestId("language-picker").click()
  await page.getByRole("menuitem", { name: "German" }).click()

  await expect(page.getByTestId("document-read-only")).toBeVisible({
    timeout: 60_000,
  })
  await expect(page.getByTestId("read-only-body")).toContainText("Fehler 407")
  await expect(page.getByTestId("language-picker")).toContainText("German")

  // Asked for again, it comes back from storage rather than being rewritten.
  await page.getByTestId("read-only-back").click()
  await page.getByTestId("language-picker").click()
  await expect(
    page.getByTestId("language-option").filter({ hasText: "German" }),
  ).toBeVisible()
})

test("editing a page leaves the new version untranslated", async ({
  page,
  request,
}) => {
  const { token, namespace, document } = await seed(request)
  await openDocument(page, namespace.slug, document.id)
  await page.getByTestId("language-picker").click()
  await page.getByRole("menuitem", { name: "German" }).click()
  await expect(page.getByTestId("read-only-body")).toBeVisible({
    timeout: 60_000,
  })

  const before = await request.get(
    `${API}/documents/${document.id}/languages`,
    { headers: auth(token) },
  )
  expect((await before.json()).available).toContain("de")

  await updateDocument(request, token, document.id, {
    content: "<p>Completely different words now.</p>",
    content_format: "html",
  })

  const after = await request.get(`${API}/documents/${document.id}/languages`, {
    headers: auth(token),
  })
  const body = await after.json()
  expect(body.version).toBe(2)
  expect(body.available, "a new version starts with no translations").toEqual(
    [],
  )
})
