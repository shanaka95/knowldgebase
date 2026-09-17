import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useRef, useState } from "react"

import type { AskCitation, AskMessagePublic } from "@/client"
import { queryKeys } from "@/lib/queryKeys"
import { streamAsk } from "@/queries/ask"
import { conversationQuery } from "@/queries/askConversations"

export type TurnPhase = "searching" | "writing" | "done" | "error"

export interface AskTurnStats {
  searched: number
  used: number
  passages: number
  truncated: boolean
  pinned: boolean
  model: string
  tookMs: number
}

export interface AskTurn {
  id: string
  question: string
  answer: string
  citations: AskCitation[]
  phase: TurnPhase
  error: string | null
  stats: AskTurnStats | null
}

export interface AskThreadOptions {
  /** The thread being read, or undefined for a new one. */
  conversationId?: string
  namespaceId?: string
  documentId?: string
  /** Read this person's own notes alongside the pages. Defaults to on. */
  includeNotes?: boolean
  /** Called with the id the server assigned when a new thread starts. */
  onConversationStarted?: (id: string) => void
}

const EMPTY_STATS: AskTurnStats = {
  searched: 0,
  used: 0,
  passages: 0,
  truncated: false,
  pinned: false,
  model: "",
  tookMs: 0,
}

function statsFrom(
  stored: Record<string, unknown> | null,
): AskTurnStats | null {
  if (!stored) return null
  return {
    ...EMPTY_STATS,
    searched: Number(stored.searched ?? 0),
    used: Number(stored.used ?? 0),
    passages: Number(stored.passages ?? 0),
    truncated: Boolean(stored.truncated),
    model: String(stored.model ?? ""),
    tookMs: Number(stored.took_ms ?? 0),
  }
}

/** Stored messages, paired back into the question-and-answer turns they were. */
export function turnsFromMessages(messages: AskMessagePublic[]): AskTurn[] {
  const turns: AskTurn[] = []
  for (const message of messages) {
    if (message.role === "user") {
      turns.push({
        id: message.id,
        question: message.content,
        answer: "",
        citations: [],
        // A question with no answer after it was interrupted; it is shown as
        // asked rather than hidden, so the thread reads the way it happened.
        phase: "done",
        error: null,
        stats: null,
      })
      continue
    }
    const open = turns[turns.length - 1]
    if (open && !open.answer) {
      open.answer = message.content
      open.citations = message.citations ?? []
      open.stats = statsFrom(
        (message.stats as Record<string, unknown> | null) ?? null,
      )
      continue
    }
    // An answer with no question before it (should not happen) still shows.
    turns.push({
      id: message.id,
      question: "",
      answer: message.content,
      citations: message.citations ?? [],
      phase: "done",
      error: null,
      stats: statsFrom(
        (message.stats as Record<string, unknown> | null) ?? null,
      ),
    })
  }
  return turns
}

/**
 * One Ask thread: the turns on screen, and the streaming of the next one.
 *
 * Turns come from two places. A thread opened from the history rail is fetched
 * once and hydrated here; a thread being typed into is built from the stream.
 * The two never fight: once this hook has seen a thread's id - because it
 * either loaded it or just started it - it stops fetching that id, so the
 * answer arriving token by token is never overwritten by a stale copy of
 * itself from the server.
 */
export function useAskThread({
  conversationId,
  namespaceId,
  documentId,
  includeNotes,
  onConversationStarted,
}: AskThreadOptions) {
  const queryClient = useQueryClient()
  const [turns, setTurns] = useState<AskTurn[]>([])
  const [busy, setBusy] = useState(false)
  // Kept here rather than read back from the server: a thread started in this
  // session is named the moment the first event arrives, and the header should
  // not wait for a round trip to say so.
  const [title, setTitle] = useState<string | undefined>(undefined)
  // The thread whose turns are already on screen.
  const [loadedId, setLoadedId] = useState<string | undefined>(undefined)
  // A thread this session has just started. The server names it a moment
  // before the URL catches up, and during that gap there is a thread on screen
  // with no id in the URL - which must not be mistaken for the reader leaving
  // it, or the answer being written would be thrown away and reloaded.
  const starting = useRef<string | null>(null)
  const controllerRef = useRef<AbortController | null>(null)
  // Deltas arrive faster than React re-renders; batching them into one string
  // keeps the thread from re-rendering per token.
  const answerRef = useRef("")

  const needsLoading = Boolean(conversationId) && conversationId !== loadedId
  const { data, isPending, error } = useQuery({
    ...conversationQuery(conversationId ?? ""),
    enabled: needsLoading,
  })

  useEffect(() => {
    if (!needsLoading || !data) return
    setTurns(turnsFromMessages(data.messages ?? []))
    setTitle(data.title)
    setLoadedId(data.id)
  }, [needsLoading, data])

  // Leaving a thread - "New", the sidebar, the back button - empties it.
  useEffect(() => {
    if (conversationId !== undefined) {
      if (starting.current === conversationId) starting.current = null
      return
    }
    if (starting.current !== null) return // the URL is still catching up
    if (loadedId !== undefined) {
      setTurns([])
      setTitle(undefined)
      setLoadedId(undefined)
    }
  }, [conversationId, loadedId])

  const abort = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
  }, [])

  useEffect(() => abort, [abort])

  const patchLast = useCallback((patch: Partial<AskTurn>) => {
    setTurns((prev) => {
      if (prev.length === 0) return prev
      const next = [...prev]
      next[next.length - 1] = { ...next[next.length - 1], ...patch }
      return next
    })
  }, [])

  const stop = useCallback(() => {
    abort()
    setBusy(false)
    setTurns((prev) => {
      if (prev.length === 0) return prev
      const next = [...prev]
      const last = next[next.length - 1]
      if (last.phase === "searching" || last.phase === "writing") {
        next[next.length - 1] = { ...last, phase: "done" }
      }
      return next
    })
  }, [abort])

  const ask = useCallback(
    async (question: string) => {
      const q = question.trim()
      if (!q) return

      abort()
      const controller = new AbortController()
      controllerRef.current = controller
      answerRef.current = ""
      setBusy(true)

      const turnId = `live-${Date.now()}`
      setTurns((prev) => [
        ...prev,
        {
          id: turnId,
          question: q,
          answer: "",
          citations: [],
          phase: "searching",
          error: null,
          stats: null,
        },
      ])

      // The id of the thread this answer lands in: the one being read, or the
      // one the server is about to create.
      let threadId = conversationId

      try {
        await streamAsk(
          {
            q,
            namespaceId,
            documentId,
            conversationId,
            includeNotes,
            signal: controller.signal,
          },
          {
            onConversation: (event) => {
              if (threadId === event.id) return
              threadId = event.id
              // Claim the id before the URL changes, or the query above would
              // fetch the thread and overwrite the answer being written.
              starting.current = event.id
              setLoadedId(event.id)
              setTitle(event.title)
              onConversationStarted?.(event.id)
            },
            onSources: (event) =>
              patchLast({
                phase: "writing",
                citations: event.citations,
                stats: {
                  searched: event.searched,
                  used: event.used,
                  passages: event.passages ?? 0,
                  truncated: event.truncated,
                  pinned: event.pinned ?? false,
                  model: event.model,
                  tookMs: 0,
                },
              }),
            onDelta: (text) => {
              answerRef.current += text
              patchLast({ answer: answerRef.current })
            },
            onError: (message) => patchLast({ phase: "error", error: message }),
            onDone: (event) =>
              setTurns((prev) => {
                if (prev.length === 0) return prev
                const next = [...prev]
                const last = next[next.length - 1]
                next[next.length - 1] = {
                  ...last,
                  phase: last.phase === "error" ? "error" : "done",
                  stats: {
                    ...(last.stats ?? EMPTY_STATS),
                    tookMs: event.took_ms,
                  },
                  citations: last.citations.map((c) => ({
                    ...c,
                    cited: event.cited.includes(c.index),
                  })),
                }
                return next
              }),
          },
        )
      } catch (err) {
        if (controller.signal.aborted) return // superseded or stopped on purpose
        patchLast({
          phase: "error",
          error:
            err instanceof Error ? err.message : "Could not reach the server.",
        })
      } finally {
        if (controllerRef.current === controller) controllerRef.current = null
        setBusy(false)
        // The rail shows this thread at the top now, with its new title. The
        // stored copy of the thread is marked stale rather than refetched: the
        // transcript on screen is already the newer one, and this thread's
        // query is switched off while it is the one being read, so nothing
        // fires until the reader comes back to it later.
        void queryClient.invalidateQueries({
          queryKey: queryKeys.askConversations.list(),
        })
        if (threadId) {
          void queryClient.invalidateQueries({
            queryKey: queryKeys.askConversations.detail(threadId),
          })
        }
      }
    },
    [
      abort,
      conversationId,
      documentId,
      // In the dependency list, not just the closure: without it a toggled
      // setting is ignored until something else happens to change.
      includeNotes,
      namespaceId,
      onConversationStarted,
      patchLast,
      queryClient,
    ],
  )

  const retry = useCallback(() => {
    const last = turns[turns.length - 1]
    if (!last?.question) return
    setTurns((prev) => prev.slice(0, -1))
    void ask(last.question)
  }, [ask, turns])

  return {
    turns,
    busy,
    title,
    ask,
    stop,
    retry,
    loading: needsLoading && isPending,
    loadError: needsLoading ? error : null,
  }
}
