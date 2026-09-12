import { AlertCircle, Scissors, Sparkles } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import type { AskState } from "@/hooks/useAsk"
import { AnswerText } from "@/lib/answerMarkdown"

interface AskAnswerPanelProps {
  state: AskState
  onCite: (index: number) => void
  onRetry: () => void
}

export function AskAnswerPanel({
  state,
  onCite,
  onRetry,
}: AskAnswerPanelProps) {
  const { phase, answer, citations, error } = state
  const writing = phase === "writing"

  // Searching, with nothing to show yet.
  if (phase === "searching") {
    return (
      <div className="flex flex-col gap-2 rounded-lg border bg-card p-4">
        <Skeleton className="h-4 w-4/5" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/5" />
      </div>
    )
  }

  if (phase === "error" && !answer) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="size-4" />
        <AlertTitle>Could not answer that</AlertTitle>
        <AlertDescription className="flex flex-col items-start gap-2">
          <span>{error ?? "Something went wrong."}</span>
          <Button variant="outline" size="sm" onClick={onRetry}>
            Try again
          </Button>
        </AlertDescription>
      </Alert>
    )
  }

  if (!answer) return null

  return (
    <div className="flex flex-col gap-3">
      <article
        className="rounded-lg border bg-card p-4 text-[0.95rem] leading-relaxed"
        data-testid="ask-answer"
        aria-busy={writing}
        aria-live="polite"
      >
        <AnswerText
          text={answer}
          maxCitation={citations.length}
          onCite={onCite}
        />
        {writing && (
          <span
            className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-foreground align-text-bottom"
            aria-hidden
          />
        )}
      </article>

      {phase === "error" && error && (
        <Alert variant="destructive">
          <AlertCircle className="size-4" />
          <AlertTitle>The answer stopped early</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {state.truncated && (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Scissors className="size-3" />
          Some long pages were shortened to fit the model's context.
        </p>
      )}

      {phase === "done" && (
        <p
          className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground"
          data-testid="ask-footer"
        >
          <Sparkles className="size-3" />
          Answered from {state.used} of {state.searched} page
          {state.searched === 1 ? "" : "s"} found
          {state.passages > state.used && <> · {state.passages} excerpts</>}
          {state.model && <> · {state.model.split("/").pop()}</>}
          {state.tookMs > 0 && <> · {(state.tookMs / 1000).toFixed(1)}s</>}
        </p>
      )}
    </div>
  )
}
