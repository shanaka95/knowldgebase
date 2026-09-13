import { Link } from "@tanstack/react-router"
import {
  ArrowDownAZ,
  Clock,
  FilePlus2,
  FileText,
  Folder,
  FolderPlus,
  LayoutGrid,
  List,
  MoreHorizontal,
} from "lucide-react"
import { useMemo, useState } from "react"

import type { DocumentSummaryPublic, FolderPublic } from "@/client"
import { DocumentTypeBadge } from "@/components/Documents/DocumentTypeBadge"
import { EmbeddingStatusIcon } from "@/components/Embeddings/EmbeddingStatusIcon"
import { EmptyState } from "@/components/Layout/EmptyState"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useCreateDocument } from "@/hooks/useKbMutations"
import { deriveEmbeddingState } from "@/lib/embeddingState"
import { relativeTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import { openDialog } from "@/stores/dialogs"

type Sort = "name" | "updated"
type View = "grid" | "list"

interface FolderContentsProps {
  namespaceId: string
  namespaceSlug: string
  folderId: string | null
  folders: FolderPublic[]
  documents: DocumentSummaryPublic[]
  canEdit: boolean
}

function readPref<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T) || fallback
  } catch {
    return fallback
  }
}

function ItemMenu({
  namespaceId,
  namespaceSlug,
  folder,
  document,
}: {
  namespaceId: string
  namespaceSlug: string
  folder?: FolderPublic
  document?: DocumentSummaryPublic
}) {
  const target = folder
    ? ({
        type: "folder",
        id: folder.id,
        namespaceId,
        namespaceSlug,
        name: folder.name,
        parentId: folder.parent_id ?? null,
      } as const)
    : document
      ? ({
          type: "document",
          id: document.id,
          namespaceId,
          namespaceSlug,
          title: document.title,
          folderId: document.folder_id ?? null,
        } as const)
      : null
  if (!target) return null
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-xs"
          className="opacity-0 transition group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
          aria-label="Actions"
          onClick={(e) => e.preventDefault()}
        >
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44">
        <DropdownMenuItem
          onClick={() => openDialog({ kind: "rename", target })}
        >
          Rename
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => openDialog({ kind: "move", target })}>
          Move to…
        </DropdownMenuItem>
        {target.type === "document" && (
          <DropdownMenuItem
            onClick={() => openDialog({ kind: "share", target })}
          >
            Share
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          variant="destructive"
          onClick={() => openDialog({ kind: "delete", target })}
        >
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function FolderContents({
  namespaceId,
  namespaceSlug,
  folderId,
  folders,
  documents,
  canEdit,
}: FolderContentsProps) {
  const [sort, setSort] = useState<Sort>(() => readPref("kb:sort", "updated"))
  const [view, setView] = useState<View>(() => readPref("kb:view", "list"))
  const createDocument = useCreateDocument()

  const setPref = (key: string, value: string) => {
    try {
      localStorage.setItem(key, value)
    } catch {
      /* ignore */
    }
  }

  const sortedFolders = useMemo(
    () =>
      [...folders].sort((a, b) =>
        sort === "name"
          ? a.name.localeCompare(b.name, undefined, { numeric: true })
          : (b.updated_at ?? "").localeCompare(a.updated_at ?? ""),
      ),
    [folders, sort],
  )
  const sortedDocs = useMemo(
    () =>
      [...documents].sort((a, b) =>
        sort === "name"
          ? a.title.localeCompare(b.title, undefined, { numeric: true })
          : (b.updated_at ?? "").localeCompare(a.updated_at ?? ""),
      ),
    [documents, sort],
  )

  const isEmpty = folders.length === 0 && documents.length === 0

  const newPage = () =>
    createDocument.mutate({ namespaceId, namespaceSlug, folderId })
  const newFolder = () =>
    openDialog({
      kind: "newFolder",
      namespaceId,
      namespaceSlug,
      parentId: folderId,
    })

  return (
    <section className="flex flex-col gap-4" data-testid="folder-contents">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Select
            value={sort}
            onValueChange={(v) => {
              setSort(v as Sort)
              setPref("kb:sort", v)
            }}
          >
            <SelectTrigger className="h-8 w-40" aria-label="Sort by">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="updated">
                <Clock className="size-4" /> Last updated
              </SelectItem>
              <SelectItem value="name">
                <ArrowDownAZ className="size-4" /> Name
              </SelectItem>
            </SelectContent>
          </Select>
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={view}
            onValueChange={(v) => {
              if (v) {
                setView(v as View)
                setPref("kb:view", v)
              }
            }}
            aria-label="View"
          >
            <ToggleGroupItem value="list" aria-label="List view">
              <List className="size-4" />
            </ToggleGroupItem>
            <ToggleGroupItem value="grid" aria-label="Grid view">
              <LayoutGrid className="size-4" />
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
        {canEdit && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={newFolder}
              data-testid="new-folder"
            >
              <FolderPlus />
              New folder
            </Button>
            <Button
              size="sm"
              onClick={newPage}
              disabled={createDocument.isPending}
              data-testid="new-page"
            >
              <FilePlus2 />
              New page
            </Button>
          </div>
        )}
      </div>

      {isEmpty ? (
        <EmptyState
          icon={FileText}
          title="Nothing here yet"
          description={
            canEdit
              ? "Create a page to start writing, or add a folder to organise this space."
              : "This folder has no pages you can see."
          }
          action={
            canEdit ? (
              <div className="flex gap-2">
                <Button onClick={newPage}>
                  <FilePlus2 />
                  New page
                </Button>
                <Button variant="outline" onClick={newFolder}>
                  <FolderPlus />
                  New folder
                </Button>
              </div>
            ) : undefined
          }
        />
      ) : view === "grid" ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {sortedFolders.map((f) => (
            <Link
              key={f.id}
              to="/s/$namespaceSlug/f/$folderId"
              params={{ namespaceSlug, folderId: f.id }}
              className="group flex items-center gap-3 rounded-lg border bg-card p-3 transition hover:border-primary/40 hover:shadow-sm"
              data-testid="folder-card"
            >
              <span className="flex size-9 items-center justify-center rounded-md bg-muted">
                <Folder className="size-4 text-muted-foreground" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">
                  {f.name}
                </span>
                <span className="block text-xs text-muted-foreground">
                  Folder
                </span>
              </span>
              {canEdit && (
                <ItemMenu
                  namespaceId={namespaceId}
                  namespaceSlug={namespaceSlug}
                  folder={f}
                />
              )}
            </Link>
          ))}
          {sortedDocs.map((d) => (
            <Link
              key={d.id}
              to="/s/$namespaceSlug/d/$documentId"
              params={{ namespaceSlug, documentId: d.id }}
              search={{ mode: "view" } as never}
              className="group flex flex-col gap-2 rounded-lg border bg-card p-3 transition hover:border-primary/40 hover:shadow-sm"
              data-testid="document-card"
            >
              <div className="flex items-start gap-2">
                <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <span className="line-clamp-2 flex-1 text-sm font-medium leading-snug">
                  {d.title}
                </span>
                {canEdit && (
                  <ItemMenu
                    namespaceId={namespaceId}
                    namespaceSlug={namespaceSlug}
                    document={d}
                  />
                )}
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <EmbeddingStatusIcon state={deriveEmbeddingState(d)} />
                <span className="truncate">
                  Updated {relativeTime(d.updated_at)}
                </span>
                <DocumentTypeBadge type={d.doc_type} className="ml-auto" />
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="w-full overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="hidden px-3 py-2 font-medium sm:table-cell">
                  Updated
                </th>
                <th className="hidden px-3 py-2 font-medium md:table-cell">
                  Index
                </th>
                <th className="w-10 px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y">
              {sortedFolders.map((f) => (
                <tr
                  key={f.id}
                  className="group hover:bg-muted/40"
                  data-testid="folder-row"
                >
                  <td className="px-3 py-2">
                    <Link
                      to="/s/$namespaceSlug/f/$folderId"
                      params={{ namespaceSlug, folderId: f.id }}
                      className="flex items-center gap-2 font-medium hover:underline"
                    >
                      <Folder className="size-4 text-muted-foreground" />
                      <span className="truncate">{f.name}</span>
                    </Link>
                  </td>
                  <td className="hidden px-3 py-2 text-muted-foreground sm:table-cell">
                    {relativeTime(f.updated_at)}
                  </td>
                  <td className="hidden px-3 py-2 text-muted-foreground md:table-cell">
                    —
                  </td>
                  <td className="px-3 py-2 text-right">
                    {canEdit && (
                      <ItemMenu
                        namespaceId={namespaceId}
                        namespaceSlug={namespaceSlug}
                        folder={f}
                      />
                    )}
                  </td>
                </tr>
              ))}
              {sortedDocs.map((d) => {
                const state = deriveEmbeddingState(d)
                return (
                  <tr
                    key={d.id}
                    className="group hover:bg-muted/40"
                    data-testid="document-row"
                  >
                    <td className="px-3 py-2">
                      <Link
                        to="/s/$namespaceSlug/d/$documentId"
                        params={{ namespaceSlug, documentId: d.id }}
                        search={{ mode: "view" } as never}
                        className="flex min-w-0 items-center gap-2 font-medium hover:underline"
                      >
                        <FileText className="size-4 shrink-0 text-muted-foreground" />
                        <span className="truncate">{d.title}</span>
                        <DocumentTypeBadge type={d.doc_type} />
                      </Link>
                    </td>
                    <td className="hidden px-3 py-2 text-muted-foreground sm:table-cell">
                      {relativeTime(d.updated_at)}
                    </td>
                    <td className="hidden px-3 py-2 md:table-cell">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1.5 text-xs",
                          state === "ready" ? "text-muted-foreground" : "",
                        )}
                      >
                        <EmbeddingStatusIcon
                          state={state}
                          hideWhenReady={false}
                          withTooltip={false}
                        />
                        {state === "ready"
                          ? "Indexed"
                          : state === "none"
                            ? "Not indexed"
                            : state.charAt(0).toUpperCase() + state.slice(1)}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      {canEdit && (
                        <ItemMenu
                          namespaceId={namespaceId}
                          namespaceSlug={namespaceSlug}
                          document={d}
                        />
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
