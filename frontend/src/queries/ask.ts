import type { AskCitation } from "@/client"

/**
 * Streaming client for `POST /api/v1/ask/stream`.
 *
 * The generated SDK is axios-based and buffers whole responses, so the answer
 * would only appear once the model had finished — ten seconds of nothing. This
 * reads the server-sent events directly instead, so sources show up in about a
 * hundred milliseconds and the answer arrives as it is written.
 */

export interface AskConversationEvent {
  id: string
  title: string
  document_id: string | null
}

export interface AskSourcesEvent {
  citations: AskCitation[]
  searched: number
  used: number
  /** excerpts sent to the model; one long page can contribute several */
  passages?: number
  /** true when the answer was written from one page the reader chose */
  pinned?: boolean
  truncated: boolean
  retrieval_ms: number
  model: string
}

export interface AskDoneEvent {
  cited: number[]
  took_ms: number
}

export interface AskStreamHandlers {
  onConversation?: (event: AskConversationEvent) => void
  onSources?: (event: AskSourcesEvent) => void
  onDelta?: (text: string) => void
  onError?: (message: string) => void
  onDone?: (event: AskDoneEvent) => void
}

export interface AskStreamRequest {
  q: string
  namespaceId?: string
  /** Answer from this page alone: no search, no reranking. */
  documentId?: string
  /** Continue a thread. Absent, the server starts one and names it. */
  conversationId?: string
  topK?: number
  /** Read this person's own notes alongside the pages. */
  includeNotes?: boolean
  signal?: AbortSignal
}

const baseUrl = () => import.meta.env.VITE_API_URL ?? ""

/** One `event:`/`data:` block from the stream. */
function parseEvent(block: string): { name: string; data: unknown } | null {
  let name = "message"
  const dataLines: string[] = []
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim()
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim())
  }
  if (dataLines.length === 0) return null
  try {
    return { name, data: JSON.parse(dataLines.join("\n")) }
  } catch {
    return null
  }
}

export async function streamAsk(
  {
    q,
    namespaceId,
    documentId,
    conversationId,
    topK,
    includeNotes,
    signal,
  }: AskStreamRequest,
  handlers: AskStreamHandlers,
): Promise<void> {
  const response = await fetch(`${baseUrl()}/api/v1/ask/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${localStorage.getItem("access_token") ?? ""}`,
      Accept: "text/event-stream",
    },
    body: JSON.stringify({
      q,
      namespace_id: namespaceId ?? null,
      document_id: documentId ?? null,
      conversation_id: conversationId ?? null,
      top_k: topK ?? null,
      // The server defaults this off so an older client cannot start reading
      // notes by accident; the interface is the thing that opts in.
      include_notes: includeNotes ?? true,
    }),
    signal,
  })

  if (!response.ok || !response.body) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (typeof body?.detail === "string") detail = body.detail
    } catch {
      /* keep the status-based message */
    }
    throw new Error(detail)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  const handle = (block: string) => {
    const event = parseEvent(block)
    if (!event) return
    switch (event.name) {
      case "conversation":
        handlers.onConversation?.(event.data as AskConversationEvent)
        break
      case "sources":
        handlers.onSources?.(event.data as AskSourcesEvent)
        break
      case "delta":
        handlers.onDelta?.((event.data as { text: string }).text)
        break
      case "error":
        handlers.onError?.((event.data as { message: string }).message)
        break
      case "done":
        handlers.onDone?.(event.data as AskDoneEvent)
        break
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // Events are separated by a blank line; anything after the last one is a
    // partial event that has to wait for the next chunk.
    const blocks = buffer.split("\n\n")
    buffer = blocks.pop() ?? ""
    for (const block of blocks) if (block.trim()) handle(block)
  }
  if (buffer.trim()) handle(buffer)
}
