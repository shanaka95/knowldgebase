import type { EmbeddingKind } from "@/client"

/**
 * Search settings live in the URL (so a search is shareable and the back button
 * works) but are also remembered locally, so the next visit to /search starts
 * from the same setup rather than the defaults.
 */

export const SEARCH_TARGETS = ["document", "summary", "chunk"] as const
export type SearchTarget = (typeof SEARCH_TARGETS)[number]

export const TARGET_LABELS: Record<SearchTarget, string> = {
  document: "Full page",
  summary: "Summary",
  chunk: "Chunks",
}

export const TARGET_HINTS: Record<SearchTarget, string> = {
  document: "The whole page, for a broad match on the topic.",
  summary: "The AI summary, which matches the gist when the wording differs.",
  chunk: "Individual sections, for finding the exact passage.",
}

/**
 * Which corpus to look in.
 *
 * Deliberately not a fourth SEARCH_TARGET. Those are the *representations of
 * one page* - whole, summary, chunk - and `toEmbeddingKinds` casts them
 * straight to the API's EmbeddingKind union, so adding "note" there would push
 * a value the API does not accept. It would also tangle the invariants:
 * "only notes" would leave the three page checkboxes as dead controls.
 */
export const SEARCH_CORPORA = ["pages", "notes"] as const
export type SearchCorpus = (typeof SEARCH_CORPORA)[number]

export const CORPUS_LABELS: Record<SearchCorpus, string> = {
  pages: "Pages",
  notes: "My notes",
}

export const CORPUS_HINTS: Record<SearchCorpus, string> = {
  pages: "Everything in the spaces you can read.",
  notes: "The notes you wrote. Nobody else can see them, or find them here.",
}

export const DEFAULT_RRF_K = 60
export const DEFAULT_CANDIDATES = 50

export interface SearchPrefs {
  bm25: boolean
  vector: boolean
  targets: SearchTarget[]
  pages: boolean
  notes: boolean
  rrfK: number
  candidates: number
}

export const DEFAULT_PREFS: SearchPrefs = {
  bm25: true,
  vector: true,
  targets: [...SEARCH_TARGETS],
  // Notes are in by default. They are the reader's own words, and leaving them
  // out of their own search would be the surprising choice.
  pages: true,
  notes: true,
  rrfK: DEFAULT_RRF_K,
  candidates: DEFAULT_CANDIDATES,
}

const STORAGE_KEY = "kb:searchPrefs"

export function isSearchTarget(value: string): value is SearchTarget {
  return (SEARCH_TARGETS as readonly string[]).includes(value)
}

/** `"document,chunk"` → `["document", "chunk"]`, dropping anything unknown. */
export function parseTargets(value: string | undefined): SearchTarget[] {
  if (value === undefined) return [...DEFAULT_PREFS.targets]
  const parsed = value
    .split(",")
    .map((t) => t.trim())
    .filter(isSearchTarget)
  // Never leave the user with nothing to search in.
  return parsed.length > 0 ? parsed : [...DEFAULT_PREFS.targets]
}

export function serializeTargets(targets: SearchTarget[]): string {
  return SEARCH_TARGETS.filter((t) => targets.includes(t)).join(",")
}

/** The API takes `EmbeddingKind[]`; our targets are exactly those values. */
export function toEmbeddingKinds(targets: SearchTarget[]): EmbeddingKind[] {
  return targets as EmbeddingKind[]
}

export function readSearchPrefs(): SearchPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_PREFS }
    const parsed = JSON.parse(raw) as Partial<SearchPrefs>
    const targets = Array.isArray(parsed.targets)
      ? parsed.targets.filter(isSearchTarget)
      : []
    const bm25 = parsed.bm25 ?? DEFAULT_PREFS.bm25
    const vector = parsed.vector ?? DEFAULT_PREFS.vector
    const pages = parsed.pages ?? DEFAULT_PREFS.pages
    const notes = parsed.notes ?? DEFAULT_PREFS.notes
    return {
      // A stored state with both methods off would 422 every query.
      bm25: bm25 || !vector,
      vector,
      targets: targets.length > 0 ? targets : [...DEFAULT_PREFS.targets],
      // And the same for the corpora, for the same reason.
      pages: pages || !notes,
      notes,
      rrfK: clampK(parsed.rrfK),
      candidates: clampCandidates(parsed.candidates),
    }
  } catch {
    return { ...DEFAULT_PREFS }
  }
}

export function writeSearchPrefs(prefs: SearchPrefs) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs))
  } catch {
    /* private browsing, quota, … — the URL still carries the state */
  }
}

export function clampK(value: unknown): number {
  const n = Number(value)
  if (!Number.isFinite(n)) return DEFAULT_RRF_K
  return Math.min(500, Math.max(1, Math.round(n)))
}

export function clampCandidates(value: unknown): number {
  const n = Number(value)
  if (!Number.isFinite(n)) return DEFAULT_CANDIDATES
  return Math.min(200, Math.max(5, Math.round(n)))
}

export const METHOD_META = {
  bm25: {
    label: "BM25",
    sublabel: "keyword",
    hint: "Exact words: names, error codes, acronyms, identifiers.",
    // amber family — lexical. The label stays `text-foreground`: the tinted
    // background is translucent, so the *-foreground tokens (meant for solid
    // fills) turn unreadable in dark mode. Colour is carried by dot + tint.
    badge: "border-warning/40 bg-warning/15 text-foreground",
    dot: "bg-warning",
    text: "text-foreground",
  },
  vector: {
    label: "Vector",
    sublabel: "semantic",
    hint: "Meaning: finds pages that say the same thing in other words.",
    // indigo/violet family — semantic
    badge: "border-primary/40 bg-primary/10 text-foreground",
    dot: "bg-primary",
    text: "text-foreground",
  },
  fulltext: {
    label: "Full-text",
    sublabel: "database",
    hint:
      "Postgres keyword search over the live page. Runs with BM25 and covers " +
      "pages written moments ago, before the AI index has caught up.",
    // emerald family — the database, not the vector store
    badge: "border-success/40 bg-success/15 text-foreground",
    dot: "bg-success",
    text: "text-foreground",
  },
} as const

export type SearchMethod = keyof typeof METHOD_META

export function methodMeta(method: string) {
  return METHOD_META[method as SearchMethod] ?? METHOD_META.bm25
}

export function targetLabel(target: string): string {
  // "page" is the full-text source, which always searches the whole live page
  // rather than one of the indexed representations.
  if (target === "page") return "live page"
  return TARGET_LABELS[target as SearchTarget] ?? target
}
