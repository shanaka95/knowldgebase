import { AlertCircle, Pin, Scissors, Sparkles } from "lucide-react"
import { useCallback, useState } from "react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import type { AskTurn } from "@/hooks/useAskThread"
import { AnswerText } from "@/lib/answerMarkdown"
import { AskBusyLine } from "./AskComposer"
import { SourceList, sourceElementId } from "./SourceList"

interface AskTurnCardProps {
  turn: AskTurn
  /** The newest turn keeps its sources open; older ones fold them away. */
  latest: boolean
  onRetry: () => void
}

export function AskTurnCard({ turn, latest, onRetry }: AskTurnCardProps) {
  const [flashed, setFlashed] = useState<number | null>(null)
  const writing = turn.phase === "writing"
  const searching = turn.phase === "searching"

  const jumpToSource = useCallback(
    (index: number) => {
      document
        .getElementById(sourceElementId(turn.id, index))
        ?.scrollIntoView({ behavior: "smooth", block: "center" })
      setFlashed(index)
      window.setTimeout(() => setFlashed(null), 1600)
    },
    [turn.id],
  )

  return (
    <article className="flex flex-col gap-3" data-testid="ask-turn">
      {turn.question && (
        <p
          className="max-w-[85%] self-end whitespace-pre-wrap rounded-2xl rounded-br-sm bg-muted px-3.5 py-2.5 text-[0.95rem]"
          data-testid="ask-question"
        >
          {turn.question}
        </p>
      )}

      {searching && (
        <>
          <AskBusyLine phase="searching" pinned={turn.stats?.pinned ?? false} />
          <div className="flex flex-col gap-2 rounded-lg border bg-card p-4">
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/5" />
          </div>
        </>
      )}

      {turn.phase === "error" && !turn.answer && (
        <Alert variant="destructive">
          <AlertCircle className="size-4" />
          <AlertTitle>Could not answer that</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-2">
            <span>{turn.error ?? "Something went wrong."}</span>
            <Button variant="outline" size="sm" onClick={onRetry}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {turn.answer && (
        <div
          className="text-[0.95rem] leading-relaxed"
          data-testid="ask-answer"
          aria-busy={writing}
          aria-live={latest ? "polite" : "off"}
        >
          <AnswerText
            text={turn.answer}
            maxCitation={turn.citations.length}
            onCite={jumpToSource}
          />
          {writing && (
            <span
              className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-foreground align-text-bottom"
              aria-hidden
            />
          )}
        </div>
      )}

      {turn.phase === "error" && turn.answer && turn.error && (
        <Alert variant="destructive">
          <AlertCircle className="size-4" />
          <AlertTitle>The answer stopped early</AlertTitle>
          <AlertDescription>{turn.error}</AlertDescription>
        </Alert>
      )}

      <SourceList
        turnId={turn.id}
        citations={turn.citations}
        showCited={turn.phase === "done" || turn.phase === "error"}
        flashed={flashed}
        defaultOpen={latest}
      />

      {turn.stats && turn.phase === "done" && <TurnFooter stats={turn.stats} />}
    </article>
  )
}

function TurnFooter({ stats }: { stats: NonNullable<AskTurn["stats"]> }) {
  return (
    <p
      className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground"
      data-testid="ask-footer"
    >
      {stats.truncated && (
        <span className="flex items-center gap-1">
          <Scissors className="size-3" />
          shortened to fit ·
        </span>
      )}
      {stats.pinned ? (
        <>
          <Pin className="size-3" />
          Answered from the one page you chose
        </>
      ) : (
        <>
          <Sparkles className="size-3" />
          Answered from {stats.used} of {stats.searched} page
          {stats.searched === 1 ? "" : "s"} found
        </>
      )}
      {stats.model && <> · {stats.model.split("/").pop()}</>}
      {stats.tookMs > 0 && <> · {(stats.tookMs / 1000).toFixed(1)}s</>}
    </p>
  )
}
