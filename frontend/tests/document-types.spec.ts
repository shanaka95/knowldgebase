import { expect, test } from "@playwright/test"
import {
  adminToken,
  createDocument,
  createNamespace,
  getDocument,
  uid,
} from "./utils/api.ts"
import { mockRetrieve } from "./utils/search.ts"
import { openDocument, waitForSaved } from "./utils/ui.ts"

/** Pick or invent a type with the header combobox. */
async function setType(page: import("@playwright/test").Page, type: string) {
  await page.getByTestId("document-type-trigger").click()
  await page.getByTestId("document-type-input").fill(type)
  await page.getByTestId("document-type-create").click()
  await expect(page.getByTestId("document-type-trigger")).toContainText(type)
}

test.describe("Page types", () => {
  test("a new type can be invented while editing and shows as a badge", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      title: `Typed ${uid()}`,
    })
    const type = `Tax assessment ${uid()}`

    await openDocument(page, ns.slug, doc.id, "edit")
    // an untyped page offers the picker, but shows no badge in view mode
    await expect(page.getByTestId("document-type-trigger")).toContainText(
      "Add type",
    )
    await setType(page, type)
    await waitForSaved(page)

    const saved = await getDocument(request, token, doc.id)
    expect(saved.doc_type).toBe(type)
    // the type is metadata: it must not create a new version or re-index
    expect(saved.version).toBe(doc.version)

    await openDocument(page, ns.slug, doc.id, "view")
    const badge = page
      .getByTestId("document-header")
      .getByTestId("document-type-badge")
    await expect(badge).toHaveText(type)
  })

  test("an existing type is suggested with its count, and can be cleared", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const type = `Invoice ${uid()}`
    await createDocument(request, token, ns.id, {
      title: `First ${uid()}`,
      doc_type: type,
    })
    const second = await createDocument(request, token, ns.id, {
      title: `Second ${uid()}`,
    })

    await openDocument(page, ns.slug, second.id, "edit")
    await page.getByTestId("document-type-trigger").click()
    const option = page
      .getByTestId("document-type-option")
      .filter({ hasText: type })
    await expect(option).toContainText("1")
    await option.click()
    await waitForSaved(page)
    expect((await getDocument(request, token, second.id)).doc_type).toBe(type)

    // clearing it removes the type entirely, and the badge with it
    await page.getByTestId("document-type-trigger").click()
    await page.getByTestId("document-type-clear").click()
    await expect(page.getByTestId("document-type-trigger")).toContainText(
      "Add type",
    )
    await waitForSaved(page)
    expect((await getDocument(request, token, second.id)).doc_type).toBeFalsy()

    await openDocument(page, ns.slug, second.id, "view")
    await expect(
      page.getByTestId("document-header").getByTestId("document-type-badge"),
    ).toHaveCount(0)
  })

  test("the badge shows in listings only for pages that have a type", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const type = `Meeting notes ${uid()}`
    const typedTitle = `Typed page ${uid()}`
    const plainTitle = `Plain page ${uid()}`
    await createDocument(request, token, ns.id, {
      title: typedTitle,
      doc_type: type,
    })
    await createDocument(request, token, ns.id, { title: plainTitle })

    await page.goto(`/s/${ns.slug}`)
    const typedRow = page
      .getByTestId("document-row")
      .filter({ hasText: typedTitle })
    await expect(typedRow.getByTestId("document-type-badge")).toHaveText(type)
    await expect(
      page
        .getByTestId("document-row")
        .filter({ hasText: plainTitle })
        .getByTestId("document-type-badge"),
    ).toHaveCount(0)

    // and on the dashboard's recent pages
    await page.goto("/")
    const recent = page.getByTestId("recent-documents")
    await expect(recent).toBeVisible()
    await expect(
      recent
        .locator("li")
        .filter({ hasText: typedTitle })
        .getByTestId("document-type-badge"),
    ).toHaveText(type)
  })

  test("search results carry the badge for typed pages only", async ({
    page,
  }) => {
    const type = `Policy ${uid()}`
    const typedTitle = `Typed hit ${uid()}`
    const plainTitle = `Plain hit ${uid()}`
    // Hybrid search only sees indexed pages, so the response is scripted here;
    // this test is about the badge, not the ranking.
    await mockRetrieve(page, () => [
      {
        title: typedTitle,
        doc_type: type,
        sources: [{ method: "bm25", target: "document", rank: 1 }],
      },
      {
        title: plainTitle,
        sources: [{ method: "bm25", target: "document", rank: 2 }],
      },
    ])

    await page.goto("/search?q=policy")
    await expect(
      page
        .getByTestId("search-result")
        .filter({ hasText: typedTitle })
        .getByTestId("document-type-badge"),
    ).toHaveText(type)
    await expect(
      page
        .getByTestId("search-result")
        .filter({ hasText: plainTitle })
        .getByTestId("document-type-badge"),
    ).toHaveCount(0)
  })
})
