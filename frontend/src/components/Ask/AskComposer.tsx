import { FileText, Loader2, Pin, Send, Square, X } from "lucide-react"
import { useCallback, useEffect, useRef } from "react"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useNamespaces } from "@/hooks/useNamespaces"
import { PagePicker, type PickedPage } from "./PagePicker"

const ALL_SPACES = "__all__"

interface AskComposerProps {
  value: string
  onValueChange: (value: string) => void
  onSubmit: () => void
  onStop: () => void
  busy: boolean
  space: string | undefined
  onSpaceChange: (space: string | undefined) => void
  /** The pinned page, if the question is about one page only. */
  page: { id: string; title: string } | null
  onPageChange: (page: PickedPage | null) => void
  /** A thread with turns in it: the placeholder invites a follow-up instead. */
  continuing: boolean
}

export function AskComposer({
  value,
  onValueChange,
  onSubmit,
  onStop,
  busy,
  space,
  onSpaceChange,
  page,
  onPageChange,
  continuing,
}: AskComposerProps) {
  const { data: namespaces } = useNamespaces()
  const ref = useRef<HTMLTextAreaElement>(null)

  // Grow with the question instead of scrolling a two-line box.
  const fitToText = useCallback((text: string) => {
    const el = ref.current
    if (!el) return
    el.style.height = "auto"
    // `text` is what produced the new scrollHeight, so the resize is tied to it.
    el.style.height = text ? `${Math.min(el.scrollHeight, 200)}px` : "auto"
  }, [])

  useEffect(() => fitToText(value), [fitToText, value])

  return (
    <div className="flex flex-col gap-2.5 rounded-xl border bg-card p-3 shadow-sm">
      {page && (
        <div
          className="flex items-center gap-2 self-start rounded-full border border-primary/40 bg-primary/10 py-1 pl-2.5 pr-1 text-xs"
          data-testid="ask-pinned-page"
        >
          <FileText className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="max-w-60 truncate font-medium">{page.title}</span>
          <span className="text-muted-foreground">only this page</span>
          <Button
            variant="ghost"
            size="icon-sm"
            className="size-5 rounded-full"
            aria-label="Ask across every page instead"
            onClick={() => onPageChange(null)}
            data-testid="ask-unpin-page"
          >
            <X className="size-3" />
          </Button>
        </div>
      )}

      <Label htmlFor="ask-question" className="sr-only">
        Your question
      </Label>
      <Textarea
        id="ask-question"
        ref={ref}
        rows={2}
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            onSubmit()
          }
        }}
        placeholder={
          page
            ? `Ask about “${page.title}”…`
            : continuing
              ? "Ask a follow-up…"
              : "Ask a question about your pages…"
        }
        className="min-h-0 resize-none border-0 bg-transparent px-1 text-base shadow-none focus-visible:ring-0 dark:bg-transparent"
        data-testid="ask-input"
      />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <PagePicker onPick={(picked) => onPageChange(picked)}>
            <Button
              variant="outline"
              size="sm"
              data-testid="ask-pick-page"
              aria-label={
                page ? "Choose a different page" : "Ask about one page"
              }
            >
              <Pin className="size-3.5" />
              {page ? "Change page" : "One page"}
            </Button>
          </PagePicker>

          {/* A pinned page already says where to look; the space would only
              contradict it. */}
          {!page && (
            <Select
              value={space ?? ALL_SPACES}
              onValueChange={(next) =>
                onSpaceChange(next === ALL_SPACES ? undefined : next)
              }
            >
              <SelectTrigger className="w-auto min-w-40" size="sm">
                <SelectValue placeholder="All spaces" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_SPACES}>All spaces</SelectItem>
                {(namespaces?.data ?? []).map((ns) => (
                  <SelectItem key={ns.id} value={ns.id}>
                    {ns.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        <div className="flex items-center gap-2">
          <span className="hidden text-xs text-muted-foreground sm:inline">
            Enter to ask · Shift+Enter for a new line
          </span>
          {busy ? (
            <Button
              variant="outline"
              onClick={onStop}
              data-testid="ask-stop"
              aria-label="Stop answering"
            >
              <Square className="size-3.5 fill-current" />
              Stop
            </Button>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  onClick={onSubmit}
                  disabled={!value.trim()}
                  data-testid="ask-submit"
                >
                  <Send className="size-4" />
                  Ask
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">
                {page
                  ? "Answered from this page alone"
                  : "Searched across every page you can read"}
              </TooltipContent>
            </Tooltip>
          )}
        </div>
      </div>
    </div>
  )
}

export function AskBusyLine({
  phase,
  pinned,
}: {
  phase: "searching" | "writing"
  pinned: boolean
}) {
  return (
    <p
      className="flex items-center gap-2 text-sm text-muted-foreground"
      data-testid="ask-status"
    >
      <Loader2 className="size-3.5 animate-spin" />
      {phase === "writing"
        ? "Writing an answer…"
        : pinned
          ? "Reading the page…"
          : "Searching your pages…"}
    </p>
  )
}
