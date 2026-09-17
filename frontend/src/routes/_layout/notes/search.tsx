import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router"
import { ListChecks, NotebookPen, Pencil, Search, X } from "lucide-react"
import { useEffect, useState } from "react"
import { z } from "zod"

import type { NoteSummaryPublic } from "@/client"
import { EmptyState } from "@/components/Layout/EmptyState"
import { PageContainer, PageHeader } from "@/components/Layout/PageContainer"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { relativeTime } from "@/lib/format"
import { noteSearchQuery } from "@/queries/userNotes"

export const Route = createFileRoute("/_layout/notes/search")({
  component: NoteSearchPage,
  validateSearch: z.object({
    q: z.string().catch(""),
    space: z.string().optional().catch(undefined),
    archived: z.boolean().optional().catch(undefined),
  }),
  staticData: { crumb: "Search notes" },
  head: () => ({ meta: [{ title: "Search notes - PlusGPT" }] }),
})

const KIND_ICON = {
  text: NotebookPen,
  checklist: ListChecks,
  drawing: Pencil,
} as const

function NoteSearchPage() {
  const search = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const [draft, setDraft] = useState(search.q)

  // Typed into the URL after a pause, so the back button walks real searches
  // rather than every keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      if (draft !== search.q) {
        navigate({ search: (prev) => ({ ...prev, q: draft }), replace: true })
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [draft, search.q, navigate])

  const includeArchived = search.archived ?? true
  const results = useQuery(
    noteSearchQuery({
      q: search.q,
      namespaceId: search.space ?? null,
      includeArchived,
    }),
  )

  return (
    <PageContainer className="flex flex-col gap-4">
      <PageHeader
        title="Search notes"
        description="Every word you have written down, including anything archived."
      />

      <div className="flex min-w-0 flex-wrap items-center gap-3">
        <div className="relative min-w-0 flex-1">
          <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
          <Input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Search your notes"
            aria-label="Search your notes"
            className="pl-8"
            data-testid="notes-search-input"
          />
          {draft && (
            <Button
              variant="ghost"
              size="icon-xs"
              className="absolute top-2 right-2"
              aria-label="Clear"
              onClick={() => setDraft("")}
            >
              <X />
            </Button>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2 text-sm">
          <Switch
            id="notes-include-archived"
            checked={includeArchived}
            onCheckedChange={(checked) =>
              navigate({
                search: (prev) => ({ ...prev, archived: checked }),
                replace: true,
              })
            }
            data-testid="notes-search-archived"
          />
          <label htmlFor="notes-include-archived">Include archived</label>
        </div>
      </div>

      <Results query={search.q} results={results} />
    </PageContainer>
  )
}

function Results({
  query,
  results,
}: {
  query: string
  results: ReturnType<typeof useQuery<NoteSummaryPublic[]>>
}) {
  if (!query.trim()) {
    return (
      <EmptyState
        icon={Search}
        title="Search your notes"
        description="Keyword search over everything you have written down. A note is findable the moment you save it."
      />
    )
  }
  if (results.isPending) {
    return (
      <div className="flex flex-col gap-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    )
  }
  const rows = results.data ?? []
  if (rows.length === 0) {
    return (
      <div data-testid="notes-search-empty">
        <EmptyState
          icon={Search}
          title="Nothing matched"
          description="No note of yours contains those words."
        />
      </div>
    )
  }

  return (
    <ul
      className="flex flex-col divide-y rounded-lg border"
      data-testid="notes-search-results"
    >
      {rows.map((note) => {
        const Icon = KIND_ICON[note.kind] ?? NotebookPen
        return (
          <li key={note.id} data-testid="notes-search-result">
            <Link
              to="/notes/$noteId"
              params={{ noteId: note.id }}
              className="flex min-w-0 items-start gap-3 p-3 hover:bg-muted/40"
            >
              <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="truncate font-medium text-sm">
                    {note.title || "Untitled"}
                  </span>
                  {note.archived && (
                    <Badge variant="outline" className="shrink-0">
                      Archived
                    </Badge>
                  )}
                </span>
                {note.preview && (
                  <span className="line-clamp-2 wrap-anywhere text-muted-foreground text-sm">
                    {note.preview}
                  </span>
                )}
              </span>
              <span className="shrink-0 text-muted-foreground text-xs">
                {relativeTime(note.updated_at)}
              </span>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}
