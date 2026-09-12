import { expect, test } from "@playwright/test"
import {
  adminToken,
  createDocument,
  createNamespace,
  uid,
} from "./utils/api.ts"

test.describe("Dashboard", () => {
  test("greeting, spaces, recent pages and index health render", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      title: `Recent ${uid()}`,
    })
    await page.goto("/")
    await expect(page.getByTestId("dashboard-greeting")).toContainText(
      /Good (morning|afternoon|evening)|Working late/,
    )
    await expect(page.getByTestId("namespace-cards")).toContainText(ns.name)
    await expect(page.getByTestId("recent-documents")).toContainText(doc.title)

    const health = page.getByTestId("index-health")
    await expect(health).toBeVisible()
    for (const label of [
      "Pages",
      "Indexed",
      "In progress",
      "Stale",
      "Failed",
    ]) {
      await expect(health).toContainText(label)
    }
    // every tile carries a number
    const numbers = await health.locator("p.tabular-nums").allInnerTexts()
    expect(numbers).toHaveLength(5)
    for (const n of numbers) expect(n).toMatch(/^\d+$/)

    // live services are all green
    for (const svc of ["db", "qdrant", "minio", "embedding", "llm", "worker"]) {
      await expect(page.getByTestId(`service-${svc}`)).toBeVisible()
    }
    await expect(page.getByTestId("worker-banner")).toHaveCount(0)
  })

  test("recent list updates after a page is created", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    await page.goto("/")
    const title = `Fresh ${uid()}`
    await createDocument(request, token, ns.id, { title })
    await page.reload()
    await expect(page.getByTestId("recent-documents")).toContainText(title)
    await page
      .getByTestId("recent-documents")
      .getByRole("link", { name: new RegExp(title) })
      .click()
    await expect(page.getByTestId("document-title")).toHaveText(title)
  })

  test("worker offline banner appears when /health reports the worker down", async ({
    page,
  }) => {
    await page.route("**/api/v1/health/", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "degraded",
          checked_at: new Date().toISOString(),
          services: {
            db: { ok: true, latency_ms: 1, detail: null },
            qdrant: { ok: true, latency_ms: 1, detail: null },
            minio: { ok: true, latency_ms: 1, detail: null },
            embedding: { ok: true, latency_ms: 1, detail: null },
            llm: { ok: false, latency_ms: 1, detail: "HTTP 503" },
            worker: { ok: false, latency_ms: 1, detail: "no heartbeat" },
          },
        }),
      }),
    )
    await page.goto("/")
    await expect(page.getByTestId("worker-banner")).toContainText(
      "Indexing worker offline",
    )
    await expect(page.getByTestId("service-worker")).toHaveAttribute(
      "title",
      "no heartbeat",
    )
    await expect(page.getByTestId("service-llm")).toHaveAttribute(
      "title",
      "HTTP 503",
    )
  })

  test("Quick create makes a page in the chosen space", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    await page.goto("/")
    await page.getByTestId("quick-new-page").click()
    await page.getByTestId(`quick-new-page-${ns.slug}`).click()
    await expect(page).toHaveURL(new RegExp(`/s/${ns.slug}/d/.+mode=edit`))
    await expect(page.getByTestId("document-title-input")).toHaveValue(
      "Untitled",
    )
  })

  test("shared card links to the shared page", async ({ page }) => {
    await page.goto("/")
    await page.getByTestId("dashboard-shared").click()
    await expect(page).toHaveURL("/shared")
    await expect(
      page.getByRole("heading", { name: "Shared with me" }),
    ).toBeVisible()
  })
})
