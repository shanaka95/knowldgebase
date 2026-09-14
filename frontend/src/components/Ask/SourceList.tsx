import { Link } from "@tanstack/react-router"
import { ChevronRight, FileText, Puzzle } from "lucide-react"
import { useState } from "react"

import type { AskCitation } from "@/client"
import { NamespaceIcon } from "@/components/Namespaces/NamespaceIcon"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useNamespaces } from "@/hooks/useNamespaces"
import { cn } from "@/lib/utils"

/** Citations repeat their numbers every turn, so the turn is part of the id. */
export const sourceElementId = (turnId: string, index: number) =>
  `ask-source-${turnId}-${index}`

interface SourceListProps {
  turnId: string
  citations: AskCitation[]
  /** Set once the answer is finished; before that nothing is marked as cited. */
  showCited: boolean
  flashed: number | null
  /** Open on the newest turn, folded away on the ones above it. */
  defaultOpen?: boolean
}

export function SourceList({
  turnId,
  citations,
  showCited,
  flashed,
  defaultOpen = false,
}: SourceListProps) {
  const [open, setOpen] = useState(defaultOpen)
  if (citations.length === 0) return null

  const cited = citations.filter((c) => c.cited).length
  const label = showCited
    ? `${citations.length} source${citations.length === 1 ? "" : "s"} · ${cited} used in the answer`
    : `Reading ${citations.length} page${citations.length === 1 ? "" : "s"}…`

  return (
    <section className="flex flex-col gap-2" aria-label="Sources">
      <Button
        variant="ghost"
        size="sm"
        className="h-auto w-fit gap-1.5 px-1.5 py-1 text-xs text-muted-foreground"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        data-testid="ask-sources-toggle"
      >
        <ChevronRight
          className={cn("size-3.5 transition-transform", open && "rotate-90")}
        />
        {label}
      </Button>

      {open && (
        <ul className="flex flex-col gap-2">
          {citations.map((citation) => (
            <SourceRow
              key={citation.index}
              turnId={turnId}
              citation={citation}
              cited={showCited && citation.cited === true}
              flashed={flashed === citation.index}
            />
          ))}
        </ul>
      )}
    </section>
  )
}

function SourceRow({
  turnId,
  citation,
  cited,
  flashed,
}: {
  turnId: string
  citation: AskCitation
  cited: boolean
  flashed: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const { data: namespaces } = useNamespaces()
  const ns = (namespaces?.data ?? []).find(
    (n) => n.id === citation.namespace_id,
  )
  const long = citation.text.length > 260

  return (
    <li
      id={sourceElementId(turnId, citation.index)}
      data-testid="ask-source"
      data-cited={cited}
      className={cn(
        "scroll-mt-20 rounded-lg border px-3 py-2.5 transition-colors",
        cited ? "border-primary/40 bg-primary/[0.04]" : "bg-card",
        flashed && "ring-2 ring-primary ring-offset-2 ring-offset-background",
      )}
    >
      <div className="flex items-start gap-2.5">
        <span
          className={cn(
            "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded border font-mono text-[0.7rem]",
            cited
              ? "border-primary/40 bg-primary/15"
              : "bg-muted text-muted-foreground",
          )}
          aria-hidden
        >
          {citation.index}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <Link
              to="/s/$namespaceSlug/d/$documentId"
              params={{
                namespaceSlug: citation.namespace_slug,
                documentId: citation.document_id,
              }}
              search={{ mode: "view" } as never}
              className="flex min-w-0 items-center gap-1.5 font-medium hover:underline"
            >
              <FileText className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="truncate">{citation.title}</span>
            </Link>
            {cited && (
              <Badge variant="secondary" className="h-5 px-1.5 text-[0.7rem]">
                cited
              </Badge>
            )}
          </div>

          {citation.chunk_title && (
            <p className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
              <Puzzle className="size-3" />
              in section “{citation.chunk_title}”
            </p>
          )}

          <p
            className={cn(
              "mt-1.5 whitespace-pre-wrap text-sm text-muted-foreground",
              !expanded && "line-clamp-3",
            )}
          >
            {citation.text}
          </p>

          {long && (
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0 text-xs"
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? "Show less" : "Show more"}
            </Button>
          )}

          <p className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
            <NamespaceIcon icon={ns?.icon} color={ns?.color} size="xs" />
            {citation.namespace_name}
          </p>
        </div>
      </div>
    </li>
  )
}
