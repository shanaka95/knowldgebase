import { expect, type Page, test } from "@playwright/test"
import { adminToken, createNamespace, TINY_PNG, uid } from "./utils/api.ts"

type Status =
  | "queued"
  | "rendering"
  | "parsing"
  | "creating"
  | "done"
  | "failed"
  | "cancelled"

interface JobFrame {
  status: Status
  pages_done?: number
  pages_total?: number
  parser?: "mineru" | "llm" | null
  error?: string | null
  document_id?: string | null
  attempts?: number
}

const JOB_ID = "33333333-3333-4333-8333-333333333333"

function job(frame: JobFrame) {
  return {
    id: JOB_ID,
    namespace_id: "22222222-2222-4222-8222-222222222222",
    namespace_slug: "office",
    folder_id: null,
    document_id: frame.document_id ?? null,
    attachment_id: null,
    title: "Quarterly report",
    prompt: null,
    filename: "report.pdf",
    content_type: "application/pdf",
    size: 77_461,
    status: frame.status,
    parser: frame.parser ?? null,
    pages_total: frame.pages_total ?? 0,
    pages_done: frame.pages_done ?? 0,
    attempts: frame.attempts ?? 0,
    max_attempts: 3,
    error: frame.error ?? null,
    started_at: "2026-09-12T08:00:00Z",
    finished_at: null,
    created_at: "2026-09-12T08:00:00Z",
  }
}

/**
 * Serve a scripted sequence of list responses: each poll advances one frame and
 * the last one repeats. Returns a counter so a test can prove polling stopped.
 */
async function mockImports(page: Page, frames: JobFrame[]) {
  const state = { polls: 0 }
  await page.route("**/api/v1/imports/?*", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    const frame = frames[Math.min(state.polls, frames.length - 1)]
    state.polls += 1
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ data: [job(frame)], count: 1 }),
    })
  })
  return state
}

const row = (page: Page) => page.getByTestId("import-row")
const pill = (page: Page) => page.getByTestId("import-status-pill")

test.describe("Imports list", () => {
  test("a job is followed from queued to imported, then polling stops", async ({
    page,
  }) => {
    const state = await mockImports(page, [
      { status: "queued" },
      { status: "rendering" },
      { status: "parsing", pages_done: 2, pages_total: 5, parser: "mineru" },
      {
        status: "done",
        pages_done: 5,
        pages_total: 5,
        parser: "mineru",
        document_id: "44444444-4444-4444-8444-444444444444",
      },
    ])

    await page.goto("/imports")
    await expect(pill(page)).toContainText("Queued")
    await expect(pill(page)).toContainText("Rendering")

    await expect(pill(page)).toContainText("Parsing")
    // progress is reported per page while the model reads them
    await expect(row(page).getByRole("progressbar")).toHaveAttribute(
      "aria-label",
      "Parsed 2 of 5 pages",
    )
    await expect(row(page)).toContainText("MinerU")

    await expect(pill(page)).toContainText("Imported")
    await expect(row(page).getByTestId("import-open-page")).toBeVisible()

    // once terminal, the list must stop hammering the API
    const settled = state.polls
    await page.waitForTimeout(5_000)
    expect(state.polls).toBe(settled)
  })

  test("a failed job shows the reason and offers a retry", async ({ page }) => {
    await mockImports(page, [
      {
        status: "failed",
        attempts: 3,
        error: "No text could be extracted from this file.",
      },
    ])
    let retried = false
    await page.route(`**/api/v1/imports/${JOB_ID}/retry`, async (route) => {
      retried = true
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(job({ status: "queued" })),
      })
    })

    await page.goto("/imports")
    await expect(pill(page)).toContainText("Failed")
    await expect(row(page)).toContainText("No text could be extracted")
    await expect(row(page)).toContainText("attempt 3/3")
    await expect(row(page).getByTestId("import-cancel")).toHaveCount(0)

    await row(page).getByTestId("import-retry").click()
    await expect.poll(() => retried).toBe(true)
  })

  test("a running job can be cancelled but not retried", async ({ page }) => {
    await mockImports(page, [
      { status: "parsing", pages_done: 1, pages_total: 3, parser: "llm" },
    ])
    let cancelled = false
    await page.route(`**/api/v1/imports/${JOB_ID}/cancel`, async (route) => {
      cancelled = true
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(job({ status: "cancelled" })),
      })
    })

    await page.goto("/imports")
    await expect(row(page).getByTestId("import-retry")).toHaveCount(0)
    // the fallback parser is called out, since its output is weaker
    await expect(row(page)).toContainText("LLM fallback")

    await row(page).getByTestId("import-cancel").click()
    await expect.poll(() => cancelled).toBe(true)
  })

  test("removing an import asks first", async ({ page }) => {
    await mockImports(page, [{ status: "cancelled" }])
    let deleted = false
    await page.route(`**/api/v1/imports/${JOB_ID}`, async (route) => {
      if (route.request().method() !== "DELETE") return route.fallback()
      deleted = true
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ message: "removed" }),
      })
    })

    await page.goto("/imports")
    await row(page).getByTestId("import-actions").click()
    await page.getByRole("menuitem", { name: "Remove from list" }).click()
    await expect(page.getByText("Remove this import?")).toBeVisible()
    expect(deleted).toBe(false)

    await page.getByTestId("import-delete-confirm").click()
    await expect.poll(() => deleted).toBe(true)
  })
})

test.describe("Import dialog", () => {
  test("rejects anything that is not a PDF or image", async ({ page }) => {
    await page.goto("/imports")
    await page.getByTestId("import-new").click()
    await expect(page.getByTestId("import-dialog")).toBeVisible()

    await page.getByTestId("import-file-input").setInputFiles({
      name: "notes.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("just text"),
    })

    await expect(page.getByTestId("import-rejection")).toContainText(
      "is not a PDF or an image",
    )
    await expect(page.getByTestId("import-file-preview")).toHaveCount(0)
    await expect(page.getByTestId("import-submit")).toBeDisabled()
  })

  test("accepts an image, offers an automatic title and can be cleared", async ({
    page,
  }) => {
    await page.goto("/imports")
    await page.getByTestId("import-new").click()
    // the space picker defaults to the first editable space once it loads, and
    // submitting stays disabled until then
    await expect(page.getByTestId("import-space-select")).not.toContainText(
      "Select a space",
      { timeout: 15_000 },
    )

    await page.getByTestId("import-file-input").setInputFiles({
      name: "Scanned invoice.png",
      mimeType: "image/png",
      buffer: TINY_PNG,
    })

    const preview = page.getByTestId("import-file-preview")
    await expect(preview).toContainText("Scanned invoice.png")
    // The title is generated from the document by default, so the field is
    // empty and disabled until someone asks to write one.
    await expect(page.getByTestId("import-auto-title")).toBeChecked()
    await expect(page.getByTestId("import-title")).toBeDisabled()
    await page.getByTestId("import-auto-title").click()
    await expect(page.getByTestId("import-title")).toBeEnabled()
    await expect(page.getByTestId("import-submit")).toBeEnabled({
      timeout: 15_000,
    })

    await page.getByTestId("import-clear-file").click()
    await expect(page.getByTestId("import-dropzone")).toBeVisible()
    await expect(page.getByTestId("import-submit")).toBeDisabled()
  })
})

test.describe("Imported pages", () => {
  /**
   * The full loop against the real parser: upload, wait for the worker to turn
   * it into a page, and confirm the original file is still reachable from it.
   */
  test("@slow an uploaded image becomes a page that keeps the original file", async ({
    page,
    request,
  }) => {
    test.setTimeout(6 * 60_000)
    const token = await adminToken(request)
    const ns = await createNamespace(request, token, {
      name: `Imports ${uid()}`,
    })
    const filename = `receipt-${uid()}.png`

    // A picture of real text: the parser rejects a blank image, so render one.
    const canvas = await page.context().newPage()
    await canvas.setViewportSize({ width: 900, height: 500 })
    await canvas.setContent(
      `<body style="font:28px Georgia;padding:48px">
         <h1>Coffee receipt</h1>
         <p>Two flat whites and one almond croissant.</p>
         <p>Total paid: fourteen euro and twenty cents.</p>
       </body>`,
    )
    const shot = await canvas.screenshot({ type: "png" })
    await canvas.close()

    await page.goto("/imports")
    await page.getByTestId("import-new").click()
    await page.getByTestId("import-file-input").setInputFiles({
      name: filename,
      mimeType: "image/png",
      buffer: shot,
    })
    // put it in this test's own space
    await page.getByTestId("import-space-select").click()
    await page.getByRole("option", { name: ns.name }).click()
    await page.getByTestId("import-submit").click()

    // submitting lands on the imports list
    await expect(page).toHaveURL(/\/imports/)
    const mine = page.getByTestId("import-row").filter({ hasText: filename })
    await expect(mine).toBeVisible({ timeout: 20_000 })

    await expect(mine.getByTestId("import-status-pill")).toContainText(
      "Imported",
      { timeout: 300_000 },
    )

    await mine.getByTestId("import-open-page").click()
    await expect(page.getByTestId("document-page")).toBeVisible({
      timeout: 20_000,
    })

    // the upload survives as the page's source file …
    const card = page.getByTestId("source-file-card")
    await expect(card).toContainText(filename)
    await expect(page.getByTestId("source-file-chip")).toBeVisible()

    // … and can be opened at any time
    await card.getByTestId("source-file-view").click()
    const dialog = page.getByTestId("source-file-dialog")
    await expect(dialog).toBeVisible()
    await expect(dialog.getByTestId("source-file-image")).toBeVisible({
      timeout: 20_000,
    })
    await expect(dialog.getByTestId("source-file-download")).toBeVisible()
  })

  test("@slow an imported PDF can be reopened from the page", async ({
    page,
    request,
  }) => {
    test.setTimeout(6 * 60_000)
    const token = await adminToken(request)
    const ns = await createNamespace(request, token, { name: `PDFs ${uid()}` })
    const filename = `handbook-${uid()}.pdf`

    // A real PDF with real text: the parser rejects a blank one, and printing
    // from the browser is the cheapest way to get a genuine file.
    const printer = await page.context().newPage()
    await printer.setContent(
      `<h1>Expense handbook</h1>
       <p>Receipts must be submitted within thirty days of the purchase date.</p>
       <p>Anything above five hundred euro needs a manager signature.</p>`,
    )
    const pdf = await printer.pdf({ format: "A4" })
    await printer.close()

    await page.goto("/imports")
    await page.getByTestId("import-new").click()
    await page.getByTestId("import-file-input").setInputFiles({
      name: filename,
      mimeType: "application/pdf",
      buffer: pdf,
    })
    await page.getByTestId("import-space-select").click()
    await page.getByRole("option", { name: ns.name }).click()
    await page.getByTestId("import-submit").click()

    const mine = page.getByTestId("import-row").filter({ hasText: filename })
    await expect(mine).toBeVisible({ timeout: 20_000 })
    await expect(mine.getByTestId("import-status-pill")).toContainText(
      "Imported",
      { timeout: 300_000 },
    )

    await mine.getByTestId("import-open-page").click()
    await expect(page.getByTestId("document-page")).toBeVisible({
      timeout: 20_000,
    })
    // the parsed text landed in the page itself
    await expect(page.getByTestId("document-page")).toContainText(/Receipts/i)

    await page
      .getByTestId("source-file-card")
      .getByTestId("source-file-view")
      .click()
    const dialog = page.getByTestId("source-file-dialog")
    await expect(dialog).toBeVisible()
    // headless Chromium paints an empty frame for PDFs, so assert the embed and
    // its download fallback exist rather than what they render
    await expect(dialog.getByTestId("source-file-pdf")).toBeVisible({
      timeout: 20_000,
    })
    await expect(dialog.getByTestId("source-file-download")).toBeVisible()
  })
})

test.describe("Importing several files at once", () => {
  const png = (name: string) => ({
    name,
    mimeType: "image/png",
    buffer: TINY_PNG,
  })

  async function openDialog(page: Page) {
    await page.goto("/imports")
    await page.getByTestId("import-new").click()
    await expect(page.getByTestId("import-space-select")).not.toContainText(
      "Select a space",
      { timeout: 15_000 },
    )
  }

  test("several files are listed and can be removed one at a time", async ({
    page,
  }) => {
    await openDialog(page)
    await page
      .getByTestId("import-file-input")
      .setInputFiles([png("one.png"), png("two.png"), png("three.png")])

    await expect(page.getByTestId("import-file-preview")).toHaveCount(3)
    await page.getByRole("button", { name: "Remove two.png" }).click()
    await expect(page.getByTestId("import-file-preview")).toHaveCount(2)
    await expect(page.getByTestId("import-dialog")).not.toContainText("two.png")
  })

  test("separate pages cannot share one title", async ({ page }) => {
    await openDialog(page)
    await page
      .getByTestId("import-file-input")
      .setInputFiles([png("one.png"), png("two.png")])

    // Two files becoming two pages: a shared title would name them identically,
    // so the field is not offered at all.
    await expect(page.getByTestId("import-title")).toBeDisabled()
    await expect(page.getByTestId("import-auto-title")).toBeDisabled()
    await expect(page.getByTestId("import-dialog")).toContainText(
      "named after its own content",
    )
  })

  test("combining them makes a title available again", async ({ page }) => {
    await openDialog(page)
    await page
      .getByTestId("import-file-input")
      .setInputFiles([png("one.png"), png("two.png")])

    await expect(page.getByTestId("import-combine")).not.toBeChecked()
    await page.getByTestId("import-combine").click()
    await expect(page.getByTestId("import-dialog")).toContainText(
      "become one page",
    )

    await page.getByTestId("import-auto-title").click()
    await expect(page.getByTestId("import-title")).toBeEnabled()
    await page.getByTestId("import-title").fill("Site survey")
    await expect(page.getByTestId("import-title")).toHaveValue("Site survey")
  })

  test("the combine choice only appears once there is more than one file", async ({
    page,
  }) => {
    await openDialog(page)
    await page.getByTestId("import-file-input").setInputFiles([png("one.png")])
    await expect(page.getByTestId("import-combine")).toBeHidden()

    await page.getByTestId("import-file-input").setInputFiles([png("two.png")])
    await expect(page.getByTestId("import-combine")).toBeVisible()
  })

  test("an unsupported file is refused without losing the good ones", async ({
    page,
  }) => {
    await openDialog(page)
    await page
      .getByTestId("import-file-input")
      .setInputFiles([
        png("keep.png"),
        { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("x") },
      ])

    await expect(page.getByTestId("import-rejection")).toBeVisible()
    await expect(page.getByTestId("import-file-preview")).toHaveCount(1)
    await expect(page.getByTestId("import-file-preview")).toContainText(
      "keep.png",
    )
  })
})
