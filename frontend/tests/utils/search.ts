import type { Page, Request } from "@playwright/test"
import { uid } from "./api.ts"

/**
 * Helpers for driving the hybrid search UI deterministically.
 *
 * The real `/search/retrieve` only sees pages that the embedding worker has
 * already indexed, which takes a minute or two per page. Tests about the
 * *interface* — badges, the explain panel, URL round-trips — therefore script
 * the response, while the real ranking behaviour is covered by the @slow test
 * in hybrid-search.spec.ts.
 */

export interface SourceHit {
  method: "bm25" | "vector"
  target: "document" | "summary" | "chunk"
  rank: number
  score?: number
  contribution?: number
  chunk_index?: number | null
  chunk_title?: string | null
}

export interface HitSpec {
  title: string
  doc_type?: string | null
  score?: number
  snippet?: string
  sources: SourceHit[]
  namespace_name?: string
  namespace_slug?: string
  matched_chunk_title?: string | null
  document_id?: string
}

/** Query parameters as the page actually sent them. */
export interface RetrieveParams {
  q: string
  bm25: boolean
  pages: boolean
  notes: boolean
  vector: boolean
  targets: string[]
  k: number | null
  namespaceId: string | null
  candidates: number | null
}

function buildHit(spec: HitSpec) {
  return {
    document_id: spec.document_id ?? `11111111-1111-4111-8111-${uid()}00000`,
    title: spec.title,
    doc_type: spec.doc_type ?? null,
    namespace_id: "22222222-2222-4222-8222-222222222222",
    namespace_slug: spec.namespace_slug ?? "office",
    namespace_name: spec.namespace_name ?? "Office",
    folder_id: null,
    score: spec.score ?? 0.05,
    snippet: spec.snippet ?? `A snippet mentioning <mark>${spec.title}</mark>.`,
    summary: null,
    updated_at: "2026-09-12T08:00:00Z",
    embedding_status: "ready",
    matched_chunk_index: spec.matched_chunk_title ? 1 : null,
    matched_chunk_title: spec.matched_chunk_title ?? null,
    sources: spec.sources.map((s) => ({
      method: s.method,
      target: s.target,
      rank: s.rank,
      score: s.score ?? 0.5,
      contribution: s.contribution ?? 1 / (60 + s.rank),
      chunk_index: s.chunk_index ?? null,
      chunk_title: s.chunk_title ?? null,
    })),
  }
}

export function parseRetrieve(request: Request): RetrieveParams {
  const url = new URL(request.url())
  const p = url.searchParams
  const k = p.get("rrf_k")
  const depth = p.get("candidates_per_source")
  return {
    q: p.get("q") ?? "",
    // the client omits a param when it equals the API default of true
    bm25: p.get("bm25") !== "false",
    // Read the way bm25 is: the client omits a parameter that
    // equals the API default, so absence means the default.
    pages: p.get("include_pages") !== "false",
    notes: p.get("include_notes") === "true",
    vector: p.get("vector") !== "false",
    targets: p.getAll("targets"),
    k: k === null ? null : Number(k),
    candidates: depth === null ? null : Number(depth),
    namespaceId: p.get("namespace_id"),
  }
}

/**
 * Intercept `/search/retrieve` and answer with `hits(params)`. The returned
 * object records every request so tests can assert what the UI asked for.
 */
export async function mockRetrieve(
  page: Page,
  hits: (params: RetrieveParams) => HitSpec[],
  options: {
    usedBm25?: (p: RetrieveParams) => boolean
    usedRerank?: boolean
  } = {},
) {
  const requests: RetrieveParams[] = []

  await page.route("**/api/v1/search/retrieve*", async (route) => {
    const params = parseRetrieve(route.request())
    requests.push(params)
    const data = hits(params).map(buildHit)
    const usedBm25 = options.usedBm25 ? options.usedBm25(params) : params.bm25
    const targets =
      params.targets.length > 0
        ? params.targets
        : ["document", "summary", "chunk"]
    const sources = [
      ...(usedBm25
        ? targets.map((t) => ({
            method: "bm25",
            target: t,
            hits: 2,
            took_ms: 9,
            error: null,
          }))
        : []),
      ...(params.vector
        ? targets.map((t) => ({
            method: "vector",
            target: t,
            hits: 4,
            took_ms: 11,
            error: null,
          }))
        : []),
    ]
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        data,
        count: data.length,
        query: params.q,
        query_tokens: params.q.split(/\s+/).filter(Boolean),
        used_bm25: usedBm25,
        used_vector: params.vector,
        used_rerank: options.usedRerank ?? false,
        targets,
        rrf_k: params.k ?? 60,
        sources,
        took_ms: 42,
      }),
    })
  })

  return {
    requests,
    last: () => requests[requests.length - 1],
  }
}
