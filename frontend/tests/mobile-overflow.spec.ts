import { expect, type Page, test } from "@playwright/test"

/**
 * A phone must never have to be scrolled sideways, and a dialog must never
 * put half of itself off the screen.
 *
 * Horizontal scrolling on a narrow screen is never a design choice — it means
 * something refused to wrap, and the reader has to drag the page around to
 * finish a sentence. Text here is user-supplied, so any element sized to its
 * content is a page waiting to break on somebody's long filename.
 *
 * Tables, diagrams and code are the exception: they are allowed to be wider
 * than the screen, inside their own scroller. The probe skips anything sitting
 * in one, and checks the page body itself instead.
 */

const PHONE = { width: 390, height: 844 }
/** An iPhone SE / small Android: the size a dialog actually gets cut off at. */
const SMALL_PHONE = { width: 360, height: 640 }

/** Long enough to widen anything that sizes to its content. */
const LONG_WORD = "Betriebskostenabrechnung".repeat(6)

async function overflowReport(page: Page) {
  return page.evaluate(() => {
    const doc = document.documentElement
    const body = document.body

    // The TanStack router and query devtools mount into the page in
    // development and are compiled out of the production build. Their panel is
    // wider than a phone when open, and whether it is open is remembered
    // between runs — so left in place they would decide the result of this
    // audit instead of the app doing so. Taken out of the document altogether,
    // rather than skipped element by element, so the page-level measurement
    // below stays the ground truth it ought to be.
    for (const panel of Array.from(
      document.querySelectorAll('[class*="TanStack"], [class*="tsqd-"]'),
    )) {
      panel.remove()
    }

    const pageOverflow = Math.max(
      doc.scrollWidth - doc.clientWidth,
      body.scrollWidth - body.clientWidth,
    )

    // Which elements stick out past the viewport, ignoring anything already
    // inside something that scrolls horizontally on purpose.
    const scrolls = (el: Element) => {
      const style = getComputedStyle(el)
      return (
        (style.overflowX === "auto" || style.overflowX === "scroll") &&
        el.scrollWidth > el.clientWidth + 1
      )
    }
    const inAllowedScroller = (el: Element) => {
      let parent = el.parentElement
      while (parent && parent !== document.body) {
        if (scrolls(parent)) return true
        parent = parent.parentElement
      }
      return false
    }

    const culprits: {
      tag: string
      cls: string
      right: number
      text: string
    }[] = []
    const limit = doc.clientWidth + 1
    for (const el of Array.from(document.body.querySelectorAll("*"))) {
      if ((el as HTMLElement).offsetParent === null && el.tagName !== "BODY") {
        continue // hidden
      }
      const style = getComputedStyle(el)
      if (style.position === "fixed") continue
      const rect = el.getBoundingClientRect()
      if (rect.width === 0 || rect.height === 0) continue
      if (rect.right <= limit) continue
      if (inAllowedScroller(el)) continue
      // Geometry inside an <svg> is measured in the drawing's own coordinates
      // and routinely reports a box past the viewport while rendering inside
      // it. The <svg> element itself is still checked.
      if ((el as SVGElement).ownerSVGElement) continue
      culprits.push({
        tag: el.tagName.toLowerCase(),
        cls: (el.getAttribute("class") ?? "").slice(0, 90),
        right: Math.round(rect.right),
        text: (el.textContent ?? "").trim().slice(0, 50),
      })
    }
    // The outermost offender is the one worth reporting; its children are
    // usually just carried along with it.
    return {
      pageOverflow,
      viewport: doc.clientWidth,
      culprits: culprits.slice(0, 6),
    }
  })
}

async function expectNoSidewaysScroll(page: Page, where: string) {
  const report = await overflowReport(page)
  const detail = report.culprits
    .map((c) => `    <${c.tag} class="${c.cls}"> right=${c.right} “${c.text}”`)
    .join("\n")
  expect(
    report.pageOverflow,
    `${where} scrolls sideways by ${report.pageOverflow}px ` +
      `(viewport ${report.viewport}px):\n${detail}`,
  ).toBeLessThanOrEqual(1)
}

/**
 * Serve the real API, with every human-written field made long.
 *
 * The seeded data has tidy short names, so a sweep over it proves only that
 * the pages survive tidy short names - which is how a 652px overflow on the
 * dashboard sat under a passing audit. Real knowledge bases are full of
 * `Betriebskostenabrechnung_2024_Hausverwaltung_final_signed.pdf`, and that is
 * the case worth testing.
 */
const LENGTHENED_FIELDS = new Set([
  "title",
  "name",
  "filename",
  "description",
  "full_name",
  "email",
  "slug",
  "doc_type",
  "question",
  "answer",
  "persona",
  "error",
  "display_name",
])

async function withLongText(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const response = await route.fetch()
    if (
      !(response.headers()["content-type"] ?? "").includes("application/json")
    ) {
      return route.fulfill({ response })
    }
    const lengthen = (node: unknown): unknown => {
      if (Array.isArray(node)) return node.map(lengthen)
      if (node && typeof node === "object") {
        return Object.fromEntries(
          Object.entries(node as Record<string, unknown>).map(
            ([key, value]) => [
              key,
              LENGTHENED_FIELDS.has(key) && typeof value === "string" && value
                ? `${LONG_WORD}_${value}`
                : lengthen(value),
            ],
          ),
        )
      }
      return node
    }
    try {
      return route.fulfill({
        response,
        body: JSON.stringify(lengthen(await response.json())),
      })
    } catch {
      return route.fulfill({ response })
    }
  })
}

const PAGES: { path: string; name: string }[] = [
  { path: "/", name: "dashboard" },
  { path: "/ask", name: "ask" },
  { path: "/search", name: "search" },
  { path: "/capture", name: "capture" },
  { path: "/agents", name: "agents" },
  { path: "/data-sources", name: "data sources" },
  { path: "/shared", name: "shared with me" },
  { path: "/settings", name: "settings" },
  { path: "/settings?tab=api-keys", name: "settings · api keys" },
  { path: "/admin", name: "admin · users" },
  { path: "/admin?tab=channels", name: "admin · channels" },
]

test.describe("on a phone", () => {
  test.use({ viewport: PHONE })

  for (const { path, name } of PAGES) {
    test(`${name} does not scroll sideways`, async ({ page }) => {
      await page.goto(path)
      await page.waitForLoadState("networkidle")
      await expectNoSidewaysScroll(page, name)
    })
  }

  test("a very long word in search does not widen the page", async ({
    page,
  }) => {
    // The text people type is not bounded by anything, and a single unbroken
    // token is the shape that breaks layouts.
    await page.goto(`/search?q=${LONG_WORD}`)
    await page.waitForLoadState("networkidle")
    await expectNoSidewaysScroll(page, "search with a very long query")
  })

  test("a long question in ask does not widen the page", async ({ page }) => {
    await page.goto("/ask")
    await page.waitForLoadState("networkidle")
    const box = page.getByRole("textbox").first()
    if (await box.isVisible().catch(() => false)) {
      await box.fill(LONG_WORD)
      await expectNoSidewaysScroll(page, "ask with a very long question")
    }
  })

  test("a failed import's error message does not widen the page", async ({
    page,
  }) => {
    // The error comes from whatever the parser said, so it is unbounded text
    // that nobody proof-read for line breaks — and it renders in an alert that
    // is indented, which is the combination that broke this page before. Served
    // from a stub so the case is here on every run, not only when an import
    // happens to have failed.
    await page.route("**/api/v1/imports/**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          count: 1,
          data: [
            {
              id: "00000000-0000-4000-8000-000000000001",
              namespace_id: "00000000-0000-4000-8000-0000000000ff",
              filename: "Betriebskostenabrechnung-2024-Nebenkosten.pdf",
              content_type: "application/pdf",
              size: 12345,
              status: "failed",
              error: `llm page parse: HTTP 404: {"error":{"code":"http_error","message":"${LONG_WORD}"}}`,
              created_at: new Date().toISOString(),
            },
          ],
        }),
      })
    })
    await page.goto("/capture")
    await page.waitForLoadState("networkidle")
    await expect(page.getByText(/llm page parse/).first()).toBeVisible()
    await expectNoSidewaysScroll(page, "capture with a failed import")
  })

  // The same pages again, on a smaller screen, with every name and title made
  // long. This is what the tidy seed data was hiding.
  for (const { path, name } of PAGES) {
    test(`${name} survives long names on a small phone`, async ({ page }) => {
      await page.setViewportSize(SMALL_PHONE)
      await withLongText(page)
      await page.goto(path)
      await page.waitForLoadState("networkidle")
      await expectNoSidewaysScroll(page, `${name} with long names`)
    })
  }

  test("the sidebar sheet does not widen the page", async ({ page }) => {
    await page.goto("/")
    await page.waitForLoadState("networkidle")
    const trigger = page
      .getByRole("button", { name: /toggle sidebar/i })
      .first()
    if (await trigger.isVisible().catch(() => false)) {
      await trigger.click()
      await page.waitForTimeout(400)
      await expectNoSidewaysScroll(page, "dashboard with the sidebar open")
    }
  })
})

/**
 * A dialog is centred by translating it half its own height, so one taller
 * than the screen hangs off both ends at once - and if it cannot scroll, the
 * title and the buttons are simply gone. This is what an import with three
 * files chosen looked like on an iPhone SE.
 */
test.describe("a dialog on a small phone", () => {
  test.use({ viewport: SMALL_PHONE })

  async function dialogReport(page: Page) {
    return page.evaluate(() => {
      const shell = document.querySelector('[data-slot="dialog-content"]')
      const body = document.querySelector('[data-slot="dialog-body"]')
      if (!(shell instanceof HTMLElement) || !(body instanceof HTMLElement)) {
        return null
      }
      const box = shell.getBoundingClientRect()
      const close = document.querySelector('[data-slot="dialog-close"]')
      const closeBox =
        close instanceof HTMLElement ? close.getBoundingClientRect() : null
      return {
        cutOffTop: box.top < -1,
        cutOffBottom: box.bottom > window.innerHeight + 1,
        sidewaysScroll: Math.max(
          document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
          0,
        ),
        closeReachable:
          !!closeBox &&
          closeBox.top >= -1 &&
          closeBox.bottom <= window.innerHeight + 1,
      }
    })
  }

  async function expectUsable(page: Page, where: string) {
    const report = await dialogReport(page)
    expect(report, `${where}: no dialog was open`).not.toBeNull()
    expect(report, `${where} is cut off or scrolls sideways`).toEqual({
      cutOffTop: false,
      cutOffBottom: false,
      sidewaysScroll: 0,
      closeReachable: true,
    })
  }

  test("the import dialog fits, with three long-named files chosen", async ({
    page,
  }) => {
    await page.goto("/capture")
    await page.waitForLoadState("networkidle")
    await page.getByTestId("import-new").click()
    const pdf = (name: string) => ({
      name,
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4"),
    })
    await page
      .locator('input[type="file"]')
      .first()
      .setInputFiles([
        pdf("Betriebskostenabrechnung_2024_Hausverwaltung_final_signed.pdf"),
        pdf("Nebenkostenabrechnung_2023_Anlage_B_unterschrieben_scan.pdf"),
        pdf("Mietvertrag_Wohnung_Norderstedt_Suedportal_7_final.pdf"),
      ])
    await expect(page.getByRole("dialog")).toBeVisible()
    await expectUsable(page, "the import dialog")

    // And scrolled to the end, where the buttons are: the close control must
    // not have scrolled away with the content.
    await page.locator('[data-slot="dialog-body"]').evaluate((node) => {
      node.scrollTop = node.scrollHeight
    })
    await expectUsable(page, "the import dialog, scrolled to the bottom")
  })

  test("the new-agent dialog fits", async ({ page }) => {
    await page.goto("/agents")
    await page.waitForLoadState("networkidle")
    await page.getByTestId("agent-new").click()
    await expect(page.getByRole("dialog")).toBeVisible()
    await expectUsable(page, "the new-agent dialog")
  })

  test("the new-API-key dialog fits", async ({ page }) => {
    await page.goto("/settings?tab=api-keys")
    await page.waitForLoadState("networkidle")
    await page.getByTestId("create-api-key").click()
    await expect(page.getByRole("dialog")).toBeVisible()
    await expectUsable(page, "the new-API-key dialog")
  })
})
