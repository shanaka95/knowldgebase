import { expect, test } from "@playwright/test"
import {
  adminToken,
  createDocument,
  createNamespace,
  uid,
} from "./utils/api.ts"
import { mockRetrieve } from "./utils/search.ts"

/**
 * The ⌘K palette (fast full-text) and the plumbing of the search page.
 * Ranking behaviour of the hybrid search itself lives in hybrid-search.spec.ts.
 */
test.describe("Search", () => {
  test("⌘K palette finds a page by a unique word and Enter opens it", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const marker = `quokka${uid()}`
    const doc = await createDocument(request, token, ns.id, {
      title: `Palette ${uid()}`,
      content: `<p>This page mentions the ${marker} animal.</p>`,
    })
    await page.goto("/")
    await expect(page.getByTestId("search-button")).toBeVisible()
    await page.keyboard.press("Meta+k")
    const input = page.getByTestId("command-input")
    await expect(input).toBeVisible()
    // empty state shows recent pages and actions — scoped to the palette, since
    // the search page carries a heading of the same name
    const palette = page.getByRole("dialog")
    await expect(palette.getByText("Recent pages")).toBeVisible()
    await expect(palette.getByText("Go to dashboard")).toBeVisible()

    await input.fill(marker)
    const result = page.getByTestId("command-result").filter({
      hasText: doc.title,
    })
    await expect(result).toBeVisible()
    await expect(result.locator("mark")).toContainText(marker)
    await page.keyboard.press("Enter")
    await expect(page).toHaveURL(new RegExp(`/s/${ns.slug}/d/${doc.id}`))
    await expect(page.getByTestId("document-title")).toHaveText(doc.title)
  })

  test("Ctrl+K also opens the palette and the header button too", async ({
    page,
  }) => {
    await page.goto("/")
    await expect(page.getByTestId("search-button")).toBeVisible()
    await page.keyboard.press("Control+k")
    await expect(page.getByTestId("command-input")).toBeVisible()
    await page.keyboard.press("Escape")
    await expect(page.getByTestId("command-input")).toBeHidden()
    await page.getByTestId("search-button").click()
    await expect(page.getByTestId("command-input")).toBeVisible()
  })

  test("palette offers full search when nothing matches", async ({ page }) => {
    await page.goto("/")
    await expect(page.getByTestId("search-button")).toBeVisible()
    await page.keyboard.press("Meta+k")
    const gibberish = `zzqqxx${uid()}`
    await page.getByTestId("command-input").fill(gibberish)
    // no page matches the literal text …
    await expect(page.getByTestId("command-result")).toHaveCount(0)
    // … but the pinned row always offers the hybrid search, which may still
    // find something by meaning
    const everything = page.getByTestId("command-search-everything")
    await expect(everything).toBeVisible()
    await expect(everything).toContainText(gibberish)
    await everything.click()
    await expect(page).toHaveURL(new RegExp(`/search\\?.*q=${gibberish}`))
  })

  test("search page lists results, links to the page and passes the space filter", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      title: `Wombat page ${uid()}`,
    })

    // Hybrid search only sees indexed pages, so the response is scripted here;
    // real ranking is covered by the @slow test in hybrid-search.spec.ts.
    const mock = await mockRetrieve(page, () => [
      {
        title: doc.title,
        document_id: doc.id,
        namespace_slug: ns.slug,
        namespace_name: ns.name,
        sources: [{ method: "bm25", target: "document", rank: 1 }],
      },
    ])

    await page.goto(`/search?q=wombat`)
    await expect(page.getByTestId("search-input")).toHaveValue("wombat")
    const result = page
      .getByTestId("search-result")
      .filter({ hasText: doc.title })
    await expect(result).toBeVisible()

    await page.getByRole("combobox", { name: "Space" }).click()
    await page.getByRole("option", { name: ns.name }).click()
    await expect(page).toHaveURL(new RegExp(`space=${ns.id}`))
    await expect.poll(() => mock.last()?.namespaceId).toBe(ns.id)

    await result.click()
    await expect(page).toHaveURL(new RegExp(`/d/${doc.id}`))
  })

  test("typing on the search page updates the URL and results", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const marker = `numbat${uid()}`
    const doc = await createDocument(request, token, ns.id, {
      title: `Titled ${marker}`,
    })
    await mockRetrieve(page, (p) =>
      p.q.includes(marker)
        ? [
            {
              title: doc.title,
              document_id: doc.id,
              namespace_slug: ns.slug,
              sources: [{ method: "vector", target: "document", rank: 1 }],
            },
          ]
        : [],
    )

    await page.goto("/search?q=")
    await expect(page.getByText("Search your knowledge base")).toBeVisible()
    await page.getByTestId("search-input").fill(marker)
    await expect(page).toHaveURL(new RegExp(`q=${marker}`))
    await expect(
      page.getByTestId("search-result").filter({ hasText: doc.title }),
    ).toBeVisible()

    await page.getByRole("button", { name: "Clear" }).click()
    await expect(page.getByText("Search your knowledge base")).toBeVisible()
  })
})
