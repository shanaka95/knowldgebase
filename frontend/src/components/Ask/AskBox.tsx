import { Loader2, Send, Square } from "lucide-react"
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
import { useNamespaces } from "@/hooks/useNamespaces"

const ALL_SPACES = "__all__"

interface AskBoxProps {
  value: string
  onValueChange: (value: string) => void
  onSubmit: () => void
  onStop: () => void
  busy: boolean
  space: string | undefined
  onSpaceChange: (space: string | undefined) => void
}

export function AskBox({
  value,
  onValueChange,
  onSubmit,
  onStop,
  busy,
  space,
  onSpaceChange,
}: AskBoxProps) {
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
    <div className="flex flex-col gap-3 rounded-lg border bg-card p-3 shadow-sm">
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
        placeholder="Ask a question about your pages…"
        className="min-h-0 resize-none border-0 bg-transparent px-1 text-base shadow-none focus-visible:ring-0 dark:bg-transparent"
        data-testid="ask-input"
      />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Select
          value={space ?? ALL_SPACES}
          onValueChange={(next) =>
            onSpaceChange(next === ALL_SPACES ? undefined : next)
          }
        >
          <SelectTrigger className="w-auto min-w-44" size="sm">
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
            <Button
              onClick={onSubmit}
              disabled={!value.trim()}
              data-testid="ask-submit"
            >
              <Send className="size-4" />
              Ask
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

export function AskBusyLine({ phase }: { phase: "searching" | "writing" }) {
  return (
    <p
      className="flex items-center gap-2 text-sm text-muted-foreground"
      data-testid="ask-status"
    >
      <Loader2 className="size-3.5 animate-spin" />
      {phase === "searching" ? "Searching your pages…" : "Writing an answer…"}
    </p>
  )
}
