import { expect, type Page, test } from "@playwright/test"
import {
  adminToken,
  createDocument,
  createNamespace,
  getEmbeddings,
  MULTI_TOPIC_MARKDOWN,
  uid,
} from "./utils/api.ts"
import { openDocument } from "./utils/ui.ts"

type Status =
  | "pending"
  | "chunking"
  | "summarizing"
  | "embedding"
  | "ready"
  | "failed"

interface Frame {
  status: Status
  stage?: string | null
  progress?: number
  jobStatus?: string
  error?: string | null
  embeddingVersion?: number | null
  version?: number
  chunkCount?: number
}

function embeddingsPayload(documentId: string, frame: Frame) {
  const version = frame.version ?? 1
  const running = ["pending", "chunking", "summarizing", "embedding"].includes(
    frame.status,
  )
  const job = {
    id: "11111111-1111-4111-8111-111111111111",
    document_id: documentId,
    doc_version: version,
    status:
      frame.jobStatus ??
      (running
        ? "running"
        : frame.status === "failed"
          ? "failed"
          : "succeeded"),
    stage: frame.stage ?? null,
    progress: frame.progress ?? 0,
    attempts: frame.status === "failed" ? 3 : 0,
    max_attempts: 3,
    run_after: "2026-09-11T10:00:00Z",
    cancel_requested: false,
    started_at: "2026-09-11T10:00:01Z",
    finished_at: running ? null : "2026-09-11T10:00:30Z",
    error: frame.error ?? null,
    chunking_method: frame.status === "ready" ? "llm" : null,
    chunk_count: frame.status === "ready" ? (frame.chunkCount ?? 2) : null,
    stats: running
      ? null
      : { stage_ms: { chunking: 7000, summarizing: 5000, embedding: 900 } },
    created_at: "2026-09-11T10:00:00Z",
  }
  const ready = frame.status === "ready"
  return {
    document_id: documentId,
    version,
    embedding_version: frame.embeddingVersion ?? (ready ? version : null),
    is_stale: ready ? (frame.embeddingVersion ?? version) !== version : true,
    embedding_status: frame.status,
    embedding_error: frame.error ?? null,
    embedding_attempts: frame.status === "failed" ? 3 : 0,
    chunk_count: ready ? (frame.chunkCount ?? 2) : 0,
    chunking_method: ready ? "llm" : null,
    embedding_updated_at: ready ? "2026-09-11T10:00:30Z" : null,
    summary: ready ? "A mocked summary of the page." : null,
    current_job: running ? job : null,
    jobs: [job],
    chunks: ready
      ? [
          {
            chunk_index: 0,
            title: "Budget",
            text: "Budget chunk text",
            char_count: 17,
            doc_version: version,
          },
          {
            chunk_index: 1,
            title: "Kitchen",
            text: "Kitchen chunk text",
            char_count: 18,
            doc_version: version,
          },
        ].slice(0, frame.chunkCount ?? 2)
      : [],
    kinds: ["document", "summary", "chunk"],
  }
}

/** Serve a scripted sequence of embedding states; the last frame repeats. */
async function mockEmbeddings(page: Page, documentId: string, frames: Frame[]) {
  let calls = 0
  await page.route(`**/api/v1/documents/${documentId}/embeddings`, (route) => {
    const frame = frames[Math.min(calls, frames.length - 1)]
    calls += 1
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(embeddingsPayload(documentId, frame)),
    })
  })
  return () => calls
}

const pill = (page: Page) => page.getByTestId("embedding-status-pill").first()

test.describe("Embedding status UI (mocked pipeline)", () => {
  test("pill walks through the pipeline and polling stops once indexed", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    const calls = await mockEmbeddings(page, doc.id, [
      { status: "pending", stage: null, jobStatus: "queued" },
      { status: "chunking", stage: "chunking", progress: 10 },
      { status: "summarizing", stage: "summarizing", progress: 40 },
      { status: "embedding", stage: "embedding", progress: 70 },
      { status: "ready", stage: "done", progress: 100 },
    ])
    await openDocument(page, ns.slug, doc.id, "view", "ai")

    await expect(pill(page)).toHaveAttribute("data-state", "pending")
    await expect(pill(page)).toContainText("Queued")
    await expect(pill(page)).toHaveAttribute("data-state", "chunking", {
      timeout: 10_000,
    })
    await expect(pill(page)).toContainText("Chunking")
    const timeline = page.getByTestId("status-timeline")
    await expect(
      timeline.locator('[data-step="chunking"][data-active]'),
    ).toBeVisible()
    await expect(pill(page)).toHaveAttribute("data-state", "summarizing", {
      timeout: 10_000,
    })
    await expect(pill(page)).toHaveAttribute("data-state", "embedding", {
      timeout: 10_000,
    })
    await expect(pill(page)).toContainText("70%")
    await expect(pill(page)).toHaveAttribute("data-state", "ready", {
      timeout: 10_000,
    })
    await expect(pill(page)).toContainText("Indexed")

    // panel shows the results
    const panel = page.getByTestId("ai-index-panel")
    await expect(panel).toHaveAttribute("data-state", "ready")
    await expect(page.getByTestId("ai-summary")).toContainText(
      "A mocked summary",
    )
    await expect(page.getByTestId("ai-chunks")).toContainText("Budget")
    await expect(page.getByTestId("ai-chunks")).toContainText("LLM semantic")
    await expect(page.getByTestId("ai-job-history")).toContainText("Succeeded")
    await expect(page.getByTestId("ai-regenerate")).toBeVisible()

    // polling stops: no more than one extra request in the next 5 s
    const after = calls()
    await page.waitForTimeout(5_000)
    expect(calls() - after).toBeLessThanOrEqual(1)
  })

  test("Regenerate confirms and calls the regenerate endpoint", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    await mockEmbeddings(page, doc.id, [{ status: "ready", stage: "done" }])
    let regenerateCalls = 0
    await page.route(
      `**/api/v1/documents/${doc.id}/embeddings/regenerate`,
      (route) => {
        regenerateCalls += 1
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(
            embeddingsPayload(doc.id, {
              status: "pending",
              jobStatus: "queued",
            }).jobs[0],
          ),
        })
      },
    )
    await openDocument(page, ns.slug, doc.id, "view", "ai")
    await page.getByTestId("ai-regenerate").click()
    const dialog = page.getByRole("alertdialog")
    await expect(dialog).toContainText("Regenerate the index?")
    await dialog.getByRole("button", { name: "Regenerate" }).click()
    await expect.poll(() => regenerateCalls).toBe(1)
  })

  test("failed state shows the error and a Retry button", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    await mockEmbeddings(page, doc.id, [
      {
        status: "failed",
        stage: "embedding",
        error: "embeddings: model server unreachable (boom)",
      },
    ])
    await openDocument(page, ns.slug, doc.id, "view", "ai")
    await expect(pill(page)).toHaveAttribute("data-state", "failed")
    await expect(pill(page)).toContainText("Failed")
    const panel = page.getByTestId("ai-index-panel")
    await expect(panel).toContainText("Indexing failed")
    await expect(panel).toContainText("model server unreachable")
    await expect(page.getByTestId("ai-retry")).toBeVisible()
    await expect(panel).toContainText("3 / 3")
  })

  test("stale state when the indexed version is older than the page", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    await mockEmbeddings(page, doc.id, [
      { status: "ready", stage: "done", version: 3, embeddingVersion: 2 },
    ])
    await openDocument(page, ns.slug, doc.id, "view", "ai")
    await expect(pill(page)).toHaveAttribute("data-state", "stale")
    await expect(pill(page)).toContainText("Stale")
    await expect(page.getByTestId("ai-index-panel")).toContainText(
      "indexed v2 · current v3",
    )
    await expect(page.getByTestId("ai-regenerate")).toBeVisible()
  })

  test("single-topic result explains why there are no chunks", async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    await page.route(`**/api/v1/documents/${doc.id}/embeddings`, (route) => {
      const body = embeddingsPayload(doc.id, { status: "ready", chunkCount: 0 })
      body.chunking_method = "llm_single_topic"
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      })
    })
    await openDocument(page, ns.slug, doc.id, "view", "ai")
    await expect(page.getByTestId("ai-chunks")).toContainText(
      "covers a single topic",
    )
    await expect(page.getByTestId("ai-index-panel")).toContainText(
      "LLM (single topic)",
    )
  })

  test("pill click toggles the AI index panel", async ({ page, request }) => {
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id)
    await mockEmbeddings(page, doc.id, [{ status: "ready" }])
    await openDocument(page, ns.slug, doc.id, "view")
    await expect(page.getByTestId("ai-index-panel")).toHaveCount(0)
    await pill(page).click()
    await expect(page).toHaveURL(/panel=ai/)
    await expect(page.getByTestId("ai-index-panel")).toBeVisible()
    await page.getByRole("button", { name: "Close AI index panel" }).click()
    await expect(page.getByTestId("ai-index-panel")).toHaveCount(0)
  })
})

test.describe("Embedding pipeline (real worker + LLM)", () => {
  test("@slow a multi-topic page gets indexed with a summary", async ({
    page,
    request,
  }) => {
    test.setTimeout(6 * 60_000)
    const token = await adminToken(request)
    const ns = await createNamespace(request, token)
    const doc = await createDocument(request, token, ns.id, {
      title: `Team notes ${uid()}`,
      content: MULTI_TOPIC_MARKDOWN,
      content_format: "markdown",
    })
    await openDocument(page, ns.slug, doc.id, "view", "ai")

    await expect(pill(page)).toHaveAttribute("data-state", "ready", {
      timeout: 330_000,
    })
    await expect(pill(page)).toContainText("Indexed")
    const panel = page.getByTestId("ai-index-panel")
    await expect(page.getByTestId("ai-summary")).not.toContainText("No summary")
    const summaryText = await page.getByTestId("ai-summary").innerText()
    expect(summaryText.length).toBeGreaterThan(40)
    await expect(panel).toContainText(/LLM/)
    await expect(page.getByTestId("ai-job-history")).toContainText("Succeeded")

    const emb = await getEmbeddings(request, token, doc.id)
    expect(emb.embedding_status).toBe("ready")
    expect(emb.embedding_version).toBe(emb.version)
    expect(emb.is_stale).toBe(false)
    expect(typeof emb.summary).toBe("string")
    expect(["llm", "llm_single_topic", "llm_windowed"]).toContain(
      emb.chunking_method,
    )
    // chunks in the UI match the API
    await expect(page.getByTestId("ai-chunks")).toContainText(
      String(emb.chunk_count),
    )
    if (emb.chunk_count > 0) {
      await expect(page.getByTestId("ai-chunks")).toContainText(
        emb.chunks[0].title,
      )
    }
  })
})
