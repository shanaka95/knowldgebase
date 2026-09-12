export type EmbeddingStatusValue =
  | "pending"
  | "chunking"
  | "summarizing"
  | "embedding"
  | "ready"
  | "failed"

export type EmbeddingState =
  | "none"
  | "pending"
  | "chunking"
  | "summarizing"
  | "embedding"
  | "ready"
  | "stale"
  | "failed"

export interface EmbeddingStateInput {
  embedding_status?: EmbeddingStatusValue | string | null
  embedding_version?: number | null
  version?: number | null
}

export const IN_PROGRESS_STATES: ReadonlySet<EmbeddingState> = new Set([
  "pending",
  "chunking",
  "summarizing",
  "embedding",
])

/**
 * Map the server's `embedding_status` + version pair to a UI state.
 * `stale` = vectors exist but belong to an older version of the document.
 */
export function deriveEmbeddingState(
  doc: EmbeddingStateInput | null | undefined,
): EmbeddingState {
  if (!doc) return "none"
  const status = doc.embedding_status
  if (!status) return "none"
  if (status === "failed") return "failed"
  if (
    status === "pending" ||
    status === "chunking" ||
    status === "summarizing" ||
    status === "embedding"
  ) {
    return status
  }
  if (status === "ready") {
    if (
      doc.embedding_version != null &&
      doc.version != null &&
      doc.embedding_version !== doc.version
    ) {
      return "stale"
    }
    return "ready"
  }
  return "none"
}

export function isEmbeddingInProgress(state: EmbeddingState): boolean {
  return IN_PROGRESS_STATES.has(state)
}

export function hasNewerChanges(
  doc: EmbeddingStateInput | null | undefined,
): boolean {
  if (!doc || doc.embedding_version == null || doc.version == null) return false
  return doc.embedding_version < doc.version
}
