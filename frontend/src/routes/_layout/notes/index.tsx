import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { Search } from "lucide-react"
import { z } from "zod"

import { PageContainer, PageHeader } from "@/components/Layout/PageContainer"
import { NoteBoard } from "@/components/Notes/NoteBoard"
import { NoteComposer } from "@/components/Notes/NoteComposer"
import { NoteToolbar } from "@/components/Notes/NoteToolbar"
import { Button } from "@/components/ui/button"

export const Route = createFileRoute("/_layout/notes/")({
  component: NotesPage,
  // Every field catches, so a hand-edited URL never throws.
  validateSearch: z.object({
    space: z.string().optional().catch(undefined),
    // Optional so a plain link to /notes needs no search object; the
    // component supplies the default.
    filter: z.enum(["active", "archived"]).optional().catch(undefined),
    kind: z.enum(["text", "checklist", "drawing"]).optional().catch(undefined),
    tag: z.string().optional().catch(undefined),
  }),
  staticData: { crumb: "Notes" },
  head: () => ({ meta: [{ title: "Notes - PlusGPT" }] }),
})

function NotesPage() {
  const search = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })

  // Patched, never replaced: a later parameter must not be dropped by an
  // earlier one's handler.
  const patch = (next: Partial<typeof search>) =>
    navigate({ search: (prev) => ({ ...prev, ...next }), replace: true })

  return (
    <PageContainer className="flex flex-col gap-4" size="wide">
      <PageHeader
        title="Notes"
        description="Yours alone. Searchable, and Ask reads them alongside your pages."
        actions={
          <Button variant="outline" size="sm" asChild>
            <a href="/notes/search">
              <Search />
              Search notes
            </a>
          </Button>
        }
      />

      <NoteComposer namespaceId={search.space ?? null} />

      <NoteToolbar
        space={search.space ?? null}
        filter={search.filter ?? "active"}
        kind={search.kind ?? null}
        tag={search.tag ?? null}
        onChange={patch}
      />

      <NoteBoard
        params={{
          namespaceId: search.space ?? null,
          kind: search.kind ?? null,
          tagId: search.tag ?? null,
          archived: search.filter === "archived",
        }}
      />
    </PageContainer>
  )
}
