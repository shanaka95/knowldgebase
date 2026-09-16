import { useQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { History, PanelRightClose, PanelRightOpen } from "lucide-react"
import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { z } from "zod"

import { AskComposer } from "@/components/Ask/AskComposer"
import { AskHistory } from "@/components/Ask/AskHistory"
import { AskIntro } from "@/components/Ask/AskIntro"
import { AskTurnCard } from "@/components/Ask/AskTurnCard"
import type { PickedPage } from "@/components/Ask/PagePicker"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { useAskThread } from "@/hooks/useAskThread"
import { useIsMobile } from "@/hooks/useMobile"
import { documentQuery } from "@/queries/documents"

const RAIL_KEY = "kb:askRailOpen"

function readRailOpen(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) !== "closed"
  } catch {
    return true
  }
}

export const Route = createFileRoute("/_layout/ask")({
  component: AskPage,
  staticData: { crumb: "Ask" },
  validateSearch: z.object({
    /** A question to ask straight away — how other pages hand one over. */
    q: z.string().catch(""),
    /** The thread being read. */
    c: z.string().optional().catch(undefined),
    /** The page the thread is pinned to. */
    doc: z.string().optional().catch(undefined),
    space: z.string().optional().catch(undefined),
  }),
  head: () => ({ meta: [{ title: "Ask - PlusGPT" }] }),
})

function AskPage() {
  const { q, c, doc, space } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const [value, setValue] = useState("")
  const [railOpen, setRailOpen] = useState(readRailOpen)
  const [mobileRail, setMobileRail] = useState(false)
  const isMobile = useIsMobile()

  const thread = useAskThread({
    conversationId: c,
    namespaceId: space,
    documentId: doc,
    onConversationStarted: (id) =>
      // `replace`, so Back leaves Ask rather than stepping through every
      // thread the reader started.
      navigate({
        search: (prev) => ({ ...prev, c: id, q: "" }),
        replace: true,
      }),
  })
  const { ask, turns, busy } = thread

  // The pinned page's name, for the chip and the empty state. The thread's own
  // copy would do, but this is already cached by the page itself.
  const { data: pinned } = useQuery({
    ...documentQuery(doc ?? ""),
    enabled: Boolean(doc),
  })

  // A question handed over in the URL (the command palette, a link) is asked
  // once and then cleared, so a refresh does not ask it again.
  const handedOver = useRef<string | null>(null)
  useEffect(() => {
    const question = q.trim()
    if (!question || c || handedOver.current === question) return
    handedOver.current = question
    void ask(question)
  }, [q, c, ask])

  const submit = (question?: string) => {
    const next = (question ?? value).trim()
    if (!next || busy) return
    setValue("")
    void ask(next)
  }

  const setPage = (page: PickedPage | null) =>
    navigate({
      search: (prev) => ({ ...prev, doc: page?.id }),
      replace: true,
    })

  const openThread = (conversation: {
    id: string
    document_id?: string | null
    namespace_id?: string | null
  }) => {
    setMobileRail(false)
    void navigate({
      search: {
        q: "",
        c: conversation.id,
        doc: conversation.document_id ?? undefined,
        space: conversation.namespace_id ?? undefined,
      },
    })
  }

  const newThread = () => {
    setMobileRail(false)
    setValue("")
    void navigate({ search: { q: "", c: undefined, doc, space } })
  }

  const toggleRail = () => {
    setRailOpen((open) => {
      try {
        localStorage.setItem(RAIL_KEY, open ? "closed" : "open")
      } catch {
        /* private browsing — the rail just forgets between visits */
      }
      return !open
    })
  }

  const page = doc ? { id: doc, title: pinned?.title ?? "this page" } : null

  return (
    // The app shell only sets a minimum height, so the height is pinned here -
    // it is what lets the transcript scroll inside the page with the composer
    // staying put, rather than the whole window scrolling away from it. No
    // `flex-1`: its `flex-basis: 0%` would win over the height on the main axis
    // and hand the page back to the content.
    <div className="flex h-[calc(100svh-3.5rem)] min-h-0 w-full">
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between gap-2 border-b px-4 py-2.5 md:px-8">
          <div className="min-w-0">
            <h1 className="truncate text-sm font-medium">
              {thread.title ?? "Ask"}
            </h1>
            {!thread.title && (
              <p className="truncate text-xs text-muted-foreground">
                Answers written from your pages, with citations.
              </p>
            )}
          </div>

          {isMobile ? (
            <Sheet open={mobileRail} onOpenChange={setMobileRail}>
              <SheetTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Chat history"
                >
                  <History className="size-4" />
                </Button>
              </SheetTrigger>
              <SheetContent side="right" className="w-80 max-w-full p-0">
                <SheetHeader className="sr-only">
                  <SheetTitle>Chat history</SheetTitle>
                </SheetHeader>
                <div className="h-full p-4">
                  <AskHistory
                    activeId={c}
                    onOpen={openThread}
                    onNew={newThread}
                    insetForClose
                  />
                </div>
              </SheetContent>
            </Sheet>
          ) : (
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={toggleRail}
              aria-label={railOpen ? "Hide chat history" : "Show chat history"}
              data-testid="ask-toggle-rail"
            >
              {railOpen ? (
                <PanelRightClose className="size-4" />
              ) : (
                <PanelRightOpen className="size-4" />
              )}
            </Button>
          )}
        </div>

        <Transcript
          turns={turns}
          loading={thread.loading}
          onRetry={thread.retry}
          onExample={submit}
          pageTitle={page?.title}
        />

        <div className="border-t px-4 py-3 md:px-8">
          <div className="mx-auto w-full max-w-3xl">
            <AskComposer
              value={value}
              onValueChange={setValue}
              onSubmit={() => submit()}
              onStop={thread.stop}
              busy={busy}
              space={space}
              onSpaceChange={(next) =>
                navigate({
                  search: (prev) => ({ ...prev, space: next }),
                  replace: true,
                })
              }
              page={page}
              onPageChange={setPage}
              continuing={turns.length > 0}
            />
          </div>
        </div>
      </section>

      {!isMobile && railOpen && (
        <aside className="hidden w-72 shrink-0 border-l p-4 md:block">
          <AskHistory activeId={c} onOpen={openThread} onNew={newThread} />
        </aside>
      )}
    </div>
  )
}

function Transcript({
  turns,
  loading,
  onRetry,
  onExample,
  pageTitle,
}: {
  turns: ReturnType<typeof useAskThread>["turns"]
  loading: boolean
  onRetry: () => void
  onExample: (question: string) => void
  pageTitle?: string
}) {
  const scroller = useRef<HTMLDivElement>(null)
  const pinnedToBottom = useRef(true)
  const seen = useRef(0)
  // Everything that should pull the view down: a new turn, and each piece of
  // the answer being written into the last one.
  const written = turns.length + (turns[turns.length - 1]?.answer.length ?? 0)

  // Follow the answer as it arrives, but only while the reader is already at
  // the bottom: scrolling up to re-read an earlier turn must not be undone by
  // the next token.
  useLayoutEffect(() => {
    const el = scroller.current
    if (!el || written === seen.current) return
    seen.current = written
    if (pinnedToBottom.current) el.scrollTop = el.scrollHeight
  }, [written])

  return (
    <div
      ref={scroller}
      onScroll={(e) => {
        const el = e.currentTarget
        pinnedToBottom.current =
          el.scrollHeight - el.scrollTop - el.clientHeight < 80
      }}
      className="min-h-0 flex-1 overflow-y-auto px-4 py-6 md:px-8"
    >
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
        {turns.length === 0 && !loading && (
          <AskIntro onExample={onExample} pageTitle={pageTitle} />
        )}
        {turns.map((turn, i) => (
          <AskTurnCard
            key={turn.id}
            turn={turn}
            latest={i === turns.length - 1}
            onRetry={onRetry}
          />
        ))}
      </div>
    </div>
  )
}
