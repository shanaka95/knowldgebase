import { useCallback, useEffect, useRef, useState } from "react"

import type { AskCitation } from "@/client"
import { type AskSourcesEvent, streamAsk } from "@/queries/ask"

export type AskPhase = "idle" | "searching" | "writing" | "done" | "error"

export interface AskState {
  phase: AskPhase
  question: string
  answer: string
  citations: AskCitation[]
  searched: number
  /** distinct pages that contributed an excerpt */
  used: number
  /** excerpts sent to the model; one long page can contribute several */
  passages: number
  truncated: boolean
  model: string
  retrievalMs: number
  tookMs: number
  error: string | null
}

const EMPTY: AskState = {
  phase: "idle",
  question: "",
  answer: "",
  citations: [],
  searched: 0,
  used: 0,
  passages: 0,
  truncated: false,
  model: "",
  retrievalMs: 0,
  tookMs: 0,
  error: null,
}

/**
 * Runs one question at a time against the streaming Ask endpoint.
 *
 * A new question aborts the one in flight, so the answer on screen always
 * belongs to the question in the box.
 */
export function useAsk() {
  const [state, setState] = useState<AskState>(EMPTY)
  const controllerRef = useRef<AbortController | null>(null)
  // Deltas arrive faster than React re-renders; batching them into one string
  // keeps the component from re-rendering per token.
  const answerRef = useRef("")

  const abort = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
  }, [])

  useEffect(() => abort, [abort])

  const stop = useCallback(() => {
    abort()
    setState((prev) =>
      prev.phase === "searching" || prev.phase === "writing"
        ? { ...prev, phase: "done" }
        : prev,
    )
  }, [abort])

  const ask = useCallback(
    async (question: string, options?: { namespaceId?: string }) => {
      const q = question.trim()
      if (!q) return

      abort()
      const controller = new AbortController()
      controllerRef.current = controller
      answerRef.current = ""

      setState({ ...EMPTY, phase: "searching", question: q })

      try {
        await streamAsk(
          { q, namespaceId: options?.namespaceId, signal: controller.signal },
          {
            onSources: (event: AskSourcesEvent) =>
              setState((prev) => ({
                ...prev,
                phase: "writing",
                citations: event.citations,
                searched: event.searched,
                used: event.used,
                passages: event.passages ?? 0,
                truncated: event.truncated,
                model: event.model,
                retrievalMs: event.retrieval_ms,
              })),
            onDelta: (text) => {
              answerRef.current += text
              setState((prev) => ({ ...prev, answer: answerRef.current }))
            },
            onError: (message) =>
              setState((prev) => ({ ...prev, phase: "error", error: message })),
            onDone: (event) =>
              setState((prev) => ({
                ...prev,
                phase: prev.phase === "error" ? "error" : "done",
                tookMs: event.took_ms,
                citations: prev.citations.map((c) => ({
                  ...c,
                  cited: event.cited.includes(c.index),
                })),
              })),
          },
        )
      } catch (error) {
        if (controller.signal.aborted) return // superseded or stopped on purpose
        setState((prev) => ({
          ...prev,
          phase: "error",
          error:
            error instanceof Error
              ? error.message
              : "Could not reach the server.",
        }))
      } finally {
        if (controllerRef.current === controller) controllerRef.current = null
      }
    },
    [abort],
  )

  const reset = useCallback(() => {
    abort()
    setState(EMPTY)
  }, [abort])

  return { ...state, ask, stop, reset }
}
