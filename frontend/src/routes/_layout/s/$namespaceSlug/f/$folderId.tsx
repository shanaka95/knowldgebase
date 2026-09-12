import { useQuery, useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { FolderOpen, MoreHorizontal } from "lucide-react"
import { Suspense } from "react"

import { PageContainer } from "@/components/Layout/PageContainer"
import { RouteErrorComponent } from "@/components/Layout/RouteErrorComponent"
import { FolderContents } from "@/components/Namespaces/FolderContents"
import { PendingHeader, PendingList } from "@/components/Pending/PendingList"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { canEditNamespace } from "@/hooks/useNamespaces"
import type { Crumb } from "@/lib/breadcrumbs"
import { folderQuery } from "@/queries/folders"
import { namespaceBySlugQuery, treeQuery } from "@/queries/namespaces"
import { openDialog } from "@/stores/dialogs"

export const Route = createFileRoute("/_layout/s/$namespaceSlug/f/$folderId")({
  component: FolderPage,
  errorComponent: RouteErrorComponent,
  loader: async ({ context: { queryClient }, params }) => {
    const [namespace, folder] = await Promise.all([
      queryClient.ensureQueryData(namespaceBySlugQuery(params.namespaceSlug)),
      queryClient.ensureQueryData(folderQuery(params.folderId)),
    ])
    const crumbs: Crumb[] = [
      { label: namespace.name, to: `/s/${namespace.slug}` },
      ...(folder.path ?? []).map((f) => ({
        label: f.name,
        to: `/s/${namespace.slug}/f/${f.id}`,
      })),
    ]
    // path already includes the folder itself when the API returns ancestors + self;
    // make sure the last crumb is this folder.
    if (!crumbs.some((c) => c.to?.endsWith(folder.id))) {
      crumbs.push({
        label: folder.name,
        to: `/s/${namespace.slug}/f/${folder.id}`,
      })
    }
    return { crumbs }
  },
  head: () => ({ meta: [{ title: "Folder - Knowledge Base" }] }),
})

function FolderPageContent() {
  const { namespaceSlug, folderId } = Route.useParams()
  const { data: namespace } = useSuspenseQuery(
    namespaceBySlugQuery(namespaceSlug),
  )
  const { data: folder } = useSuspenseQuery(folderQuery(folderId))
  // the tree is the single source for children so the sidebar and page stay in sync
  const { data: index } = useQuery(treeQuery(namespace.id))
  const canEdit = canEditNamespace(namespace)

  const folders = index ? index.childrenOf(folder.id) : (folder.folders ?? [])
  const documents = index ? index.docsOf(folder.id) : (folder.documents ?? [])
  const parents = (folder.path ?? []).filter((f) => f.id !== folder.id)

  return (
    <>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-4">
          <span className="flex size-12 shrink-0 items-center justify-center rounded-lg bg-muted">
            <FolderOpen className="size-6 text-muted-foreground" />
          </span>
          <div className="min-w-0">
            <p className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
              <Link
                to="/s/$namespaceSlug"
                params={{ namespaceSlug: namespace.slug }}
                className="hover:text-foreground"
              >
                {namespace.name}
              </Link>
              {parents.map((p) => (
                <span key={p.id} className="flex items-center gap-1">
                  <span>/</span>
                  <Link
                    to="/s/$namespaceSlug/f/$folderId"
                    params={{ namespaceSlug: namespace.slug, folderId: p.id }}
                    className="hover:text-foreground"
                  >
                    {p.name}
                  </Link>
                </span>
              ))}
            </p>
            <h1
              className="truncate text-2xl font-semibold tracking-tight"
              data-testid="folder-title"
            >
              {folder.name}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {folders.length} folder{folders.length === 1 ? "" : "s"} ·{" "}
              {documents.length} page
              {documents.length === 1 ? "" : "s"}
            </p>
          </div>
        </div>
        {canEdit && (
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="icon" aria-label="Folder actions">
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              {(() => {
                const target = {
                  type: "folder",
                  id: folder.id,
                  namespaceId: namespace.id,
                  namespaceSlug: namespace.slug,
                  name: folder.name,
                  parentId: folder.parent_id ?? null,
                } as const
                return (
                  <>
                    <DropdownMenuItem
                      onClick={() => openDialog({ kind: "rename", target })}
                    >
                      Rename
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => openDialog({ kind: "move", target })}
                    >
                      Move to…
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      variant="destructive"
                      onClick={() => openDialog({ kind: "delete", target })}
                    >
                      Delete folder
                    </DropdownMenuItem>
                  </>
                )
              })()}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      <FolderContents
        namespaceId={namespace.id}
        namespaceSlug={namespace.slug}
        folderId={folder.id}
        folders={folders}
        documents={documents}
        canEdit={canEdit}
      />
    </>
  )
}

function FolderPage() {
  return (
    <PageContainer className="flex flex-col gap-8">
      <Suspense
        fallback={
          <>
            <PendingHeader />
            <PendingList />
          </>
        }
      >
        <FolderPageContent />
      </Suspense>
    </PageContainer>
  )
}
