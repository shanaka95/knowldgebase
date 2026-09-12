import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useCallback, useEffect, useState } from "react"
import { z } from "zod"

import { AskAnswerPanel } from "@/components/Ask/AskAnswerPanel"
import { AskBox, AskBusyLine } from "@/components/Ask/AskBox"
import { AskIntro } from "@/components/Ask/AskIntro"
import { SourceList, sourceElementId } from "@/components/Ask/SourceList"
import { PageContainer, PageHeader } from "@/components/Layout/PageContainer"
import { useAsk } from "@/hooks/useAsk"

export const Route = createFileRoute("/_layout/ask")({
  component: AskPage,
  staticData: { crumb: "Ask" },
  validateSearch: z.object({
    q: z.string().catch(""),
    space: z.string().optional().catch(undefined),
  }),
  head: () => ({ meta: [{ title: "Ask - Knowledge Base" }] }),
})

function AskPage() {
  const { q, space } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const [value, setValue] = useState(q)
  const [flashed, setFlashed] = useState<number | null>(null)
  const state = useAsk()
  const { ask, reset } = state

  // The question in the URL is the source of truth, so a shared link (and the
  // back button) reproduce the answer. This runs once per question: under
  // StrictMode's double mount the first attempt is aborted and the second one
  // completes, which is why there is no "already asked" guard here.
  useEffect(() => {
    const question = q.trim()
    if (!question) {
      reset()
      return
    }
    setValue(q)
    void ask(question, { namespaceId: space })
  }, [q, space, ask, reset])

  const submit = (question?: string) => {
    const next = (question ?? value).trim()
    if (!next) return
    if (question) setValue(question)
    if (next === q.trim()) {
      // Same question: the URL does not change, so nothing would re-trigger it.
      void ask(next, { namespaceId: space })
      return
    }
    navigate({ search: (prev) => ({ ...prev, q: next }) })
  }

  const jumpToSource = useCallback((index: number) => {
    document
      .getElementById(sourceElementId(index))
      ?.scrollIntoView({ behavior: "smooth", block: "center" })
    setFlashed(index)
    window.setTimeout(() => setFlashed(null), 1600)
  }, [])

  const busy = state.phase === "searching" || state.phase === "writing"
  const answered = state.phase !== "idle"

  return (
    <PageContainer className="flex flex-col gap-6" size="default">
      <PageHeader
        title="Ask"
        description="A question goes to every page you can read; the answer is written from the best matches and cites them."
      />

      <AskBox
        value={value}
        onValueChange={setValue}
        onSubmit={() => submit()}
        onStop={state.stop}
        busy={busy}
        space={space}
        onSpaceChange={(next) =>
          navigate({ search: (prev) => ({ ...prev, space: next }) })
        }
      />

      {!answered ? (
        <AskIntro onExample={(example) => submit(example)} />
      ) : (
        <div className="flex flex-col gap-5">
          {busy && (
            <AskBusyLine
              phase={state.phase === "searching" ? "searching" : "writing"}
            />
          )}

          <AskAnswerPanel
            state={state}
            onCite={jumpToSource}
            onRetry={() => submit(state.question)}
          />

          <SourceList
            citations={state.citations}
            showCited={state.phase === "done" || state.phase === "error"}
            flashed={flashed}
          />
        </div>
      )}
    </PageContainer>
  )
}
