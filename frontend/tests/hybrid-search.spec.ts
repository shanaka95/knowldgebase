import { expect, type Page, test } from "@playwright/test"
import {
  adminToken,
  createDocument,
  createNamespace,
  uid,
  waitForIndexed,
} from "./utils/api.ts"
import { type HitSpec, mockRetrieve } from "./utils/search.ts"

const badges = (page: Page) => page.getByTestId("source-badge")
const results = (page: Page) => page.getByTestId("search-result")
const explainRows = (page: Page) => page.getByTestId("explain-row")

async function openExplain(page: Page) {
  await page.getByText("How these results were ranked").click()
  await expect(explainRows(page).first()).toBeVisible()
}

/** One page found by both methods, used by most of the interface tests. */
const BOTH_METHODS: HitSpec[] = [
  {
    title: "Connecting to the office VPN",
    score: 0.066,
    snippet: "Error <mark>407</mark> means your <mark>token</mark> expired.",
    matched_chunk_title: "Troubleshooting",
    sources: [
      { method: "bm25", target: "document", rank: 1, score: 8.9 },
      { method: "bm25", target: "summary", rank: 1, score: 7.2 },
      { method: "vector", target: "document", rank: 1, score: 0.68 },
      { method: "vector", target: "chunk", rank: 2, score: 0.61 },
    ],
  },
  {
    title: "Team notes, week 37",
    score: 0.031,
    sources: [{ method: "vector", target: "summary", rank: 3, score: 0.4 }],
  },
]

test.describe("Hybrid search interface", () => {
  test("a result explains which methods and targets matched it", async ({
    page,
  }) => {
    await mockRetrieve(page, () => BOTH_METHODS)
    await page.goto("/search?q=error%20407%20vpn%20token")

    const top = results(page).first()
    await expect(top).toContainText("Connecting to the office VPN")
    // the chunk that matched is named …
    await expect(top).toContainText("in section “Troubleshooting”")
    // … the snippet keeps the server's highlighting …
    await expect(top.locator("mark").first()).toHaveText("407")
    // … and every source that ranked the page is shown
    const topBadges = top.getByTestId("source-badge")
    await expect(topBadges).toHaveCount(4)
    await expect(topBadges.nth(0)).toContainText("BM25")
    await expect(top.getByTestId("fused-score")).toHaveText("0.066")
  })

  test("turning off BM25 keeps vector locked on and drops keyword badges", async ({
    page,
  }) => {
    const mock = await mockRetrieve(page, (p) =>
      // a keyword-free run keeps only the semantic sources
      BOTH_METHODS.map((h) => ({
        ...h,
        sources: h.sources.filter((s) => p.bm25 || s.method !== "bm25"),
      })).filter((h) => h.sources.length > 0),
    )
    await page.goto("/search?q=vpn%20token")
    await expect(badges(page).filter({ hasText: "BM25" }).first()).toBeVisible()

    await page.getByTestId("method-bm25").click()

    await expect(page).toHaveURL(/bm25=false/)
    // the remaining method cannot also be switched off
    await expect(page.getByTestId("method-vector")).toBeDisabled()
    await expect.poll(() => mock.last()?.bm25).toBe(false)
    await expect(badges(page).filter({ hasText: "BM25" })).toHaveCount(0)
    await expect(
      badges(page).filter({ hasText: "Vector" }).first(),
    ).toBeVisible()
  })

  test("the explain panel reports one row per source that ran", async ({
    page,
  }) => {
    await mockRetrieve(page, () => BOTH_METHODS)
    await page.goto("/search?q=vpn")

    await openExplain(page)
    // 2 methods × 3 targets
    await expect(explainRows(page)).toHaveCount(6)
    await expect(explainRows(page).filter({ hasText: "BM25" })).toHaveCount(3)
    await expect(explainRows(page).filter({ hasText: "Vector" })).toHaveCount(3)

    await page.getByTestId("method-bm25").click()
    await expect(explainRows(page)).toHaveCount(3)
    await expect(explainRows(page).filter({ hasText: "BM25" })).toHaveCount(0)
  })

  test("choosing where to search changes the targets that are queried", async ({
    page,
  }) => {
    const mock = await mockRetrieve(page, () => BOTH_METHODS)
    await page.goto("/search?q=vpn")
    await expect.poll(() => mock.last()?.targets.length).toBe(3)

    // drop "Full page" and "Summary", leaving chunks only
    await page.getByTestId("target-document").click()
    await page.getByTestId("target-summary").click()

    await expect(page).toHaveURL(/targets=chunk/)
    await expect.poll(() => mock.last()?.targets).toEqual(["chunk"])
    await expect(page.getByTestId("target-chunk")).toBeDisabled()

    await openExplain(page)
    await expect(explainRows(page)).toHaveCount(2) // 2 methods × 1 target
  })

  test("advanced settings round-trip through the URL", async ({ page }) => {
    const mock = await mockRetrieve(page, () => BOTH_METHODS)
    await page.goto("/search?q=vpn")

    await page.getByTestId("search-advanced").click()
    await page.getByTestId("rrf-k").fill("10")
    await expect(page).toHaveURL(/k=10/)
    await expect.poll(() => mock.last()?.k).toBe(10)

    await page.getByTestId("candidates").fill("25")
    await expect(page).toHaveURL(/depth=25/)
    await expect.poll(() => mock.last()?.candidates).toBe(25)

    await page.keyboard.press("Escape")
    await openExplain(page)
    await expect(page.getByTestId("search-results")).toContainText(
      "Fusion constant k = 10",
    )
  })

  test("method choices are remembered on the next visit", async ({ page }) => {
    await mockRetrieve(page, () => BOTH_METHODS)
    await page.goto("/search?q=vpn")
    await page.getByTestId("method-bm25").click()
    await expect(page).toHaveURL(/bm25=false/)

    // a plain link with no method in it falls back to the remembered choice
    await page.goto("/search?q=vpn")
    await expect(page.getByTestId("method-bm25")).not.toBeChecked()
    await expect(page.getByTestId("method-vector")).toBeDisabled()

    await page.getByTestId("method-bm25").click()
    await page.goto("/search?q=vpn")
    await expect(page.getByTestId("method-bm25")).toBeChecked()
  })

  test("a query with no keywords explains that only semantic search ran", async ({
    page,
  }) => {
    await mockRetrieve(page, () => [BOTH_METHODS[1]], { usedBm25: () => false })
    await page.goto("/search?q=how%20is%20it")

    await expect(page.getByTestId("search-results")).toContainText(
      "no keywords",
    )
    await openExplain(page)
    await expect(page.getByTestId("search-results")).toContainText(
      "Keyword search was skipped",
    )
  })

  test("an empty result set suggests widening the search", async ({ page }) => {
    await mockRetrieve(page, () => [])
    await page.goto("/search?q=nothingmatchesthis&bm25=true&vector=false")

    await expect(page.getByTestId("search-results")).toContainText(
      "No results for",
    )
    await page.getByRole("button", { name: "Enable both methods" }).click()
    await expect(page).toHaveURL(/vector=true/)
  })

  test("the explain panel says whether a reranker set the order", async ({
    page,
  }) => {
    await mockRetrieve(page, () => BOTH_METHODS, { usedRerank: true })
    await page.goto("/search?q=vpn+token")
    await expect(results(page).first()).toBeVisible()
    await openExplain(page)
    await expect(page.getByText("Reranking: on")).toBeVisible()
    await expect(page.getByText(/A reranker read your query/)).toBeVisible()
  })

  test("and says so when it did not run", async ({ page }) => {
    await mockRetrieve(page, () => BOTH_METHODS)
    await page.goto("/search?q=vpn+token")
    await expect(results(page).first()).toBeVisible()
    await openExplain(page)
    await expect(page.getByText("Reranking: off")).toBeVisible()
    await expect(page.getByText(/A reranker read your query/)).toBeHidden()
  })
})

test.describe("Hybrid search against the real index", () => {
  /**
   * The only test here that waits for the embedding worker. It proves the two
   * halves genuinely differ: an invented token is reachable only by keyword,
   * and a paraphrase only by meaning.
   */
  test("@slow keyword and semantic search find different pages", async ({
    page,
    request,
  }) => {
    test.setTimeout(6 * 60_000)
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const rareToken = `zx9-quokka-${uid()}`

    const lexical = await createDocument(request, token, ns.id, {
      title: `Asset register ${uid()}`,
      content: `<p>The serial number ${rareToken} identifies the spare laptop kept in the cupboard.</p>`,
    })
    const semantic = await createDocument(request, token, ns.id, {
      title: `Travel policy ${uid()}`,
      content:
        "<p>Staff should book flights at least fourteen days ahead and always choose economy class on journeys under six hours. Receipts must be submitted within a month.</p>",
    })

    await waitForIndexed(request, token, lexical.id)
    await waitForIndexed(request, token, semantic.id)

    // 1. keyword only: the invented token is an exact match nothing else has
    await page.goto(
      `/search?q=${rareToken}&bm25=true&vector=false&space=${ns.id}`,
    )
    const lexicalHit = results(page).filter({ hasText: lexical.title })
    await expect(lexicalHit).toBeVisible({ timeout: 30_000 })
    await expect(
      lexicalHit
        .getByTestId("source-badge")
        .filter({ hasText: "BM25" })
        .first(),
    ).toBeVisible()

    // 2. semantic only: a paraphrase that shares no distinctive words
    await page.goto(
      `/search?q=${encodeURIComponent("rules about booking business trips")}&bm25=false&vector=true&space=${ns.id}`,
    )
    const semanticHit = results(page).filter({ hasText: semantic.title })
    await expect(semanticHit).toBeVisible({ timeout: 30_000 })
    await expect(
      semanticHit
        .getByTestId("source-badge")
        .filter({ hasText: "Vector" })
        .first(),
    ).toBeVisible()

    // 3. both on: the keyword page is still found, now with fused sources.
    // The methods are named explicitly because the page otherwise reuses the
    // remembered choice from step 2.
    await page.goto(
      `/search?q=${rareToken}&bm25=true&vector=true&space=${ns.id}`,
    )
    await expect(results(page).filter({ hasText: lexical.title })).toBeVisible({
      timeout: 30_000,
    })
    await openExplain(page)
    // 2 methods x 3 targets, plus the Postgres full-text source that keyword
    // search adds so pages are findable before the AI index catches up
    await expect(explainRows(page)).toHaveCount(7)
    await expect(
      explainRows(page).filter({ hasText: "Full-text" }),
    ).toHaveCount(1)
  })
})
