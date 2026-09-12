export const CHUNKING_METHOD_LABELS: Record<string, string> = {
  none_short: "Skipped (short page)",
  llm_single_topic: "LLM (single topic)",
  llm: "LLM semantic",
  llm_windowed: "LLM windowed",
  fallback_headings: "Fallback: headings",
  fallback_paragraphs: "Fallback: paragraphs",
}

export function chunkingMethodLabel(method: string | null | undefined): string {
  if (!method) return "—"
  return CHUNKING_METHOD_LABELS[method] ?? method.replace(/_/g, " ")
}

export const JOB_STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
  superseded: "Superseded",
}

export const JOB_STAGE_LABELS: Record<string, string> = {
  claimed: "Claimed",
  loading: "Loading",
  chunking: "Chunking",
  summarizing: "Summarizing",
  embedding: "Embedding",
  writing: "Writing",
  done: "Done",
}
