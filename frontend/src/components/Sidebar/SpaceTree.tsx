import { Link, useNavigate, useParams } from "@tanstack/react-router"
import {
  ChevronRight,
  FilePlus2,
  FileText,
  Folder,
  FolderOpen,
  MoreHorizontal,
  Plus,
} from "lucide-react"
import { Fragment, useEffect, useMemo } from "react"

import type { DocumentSummaryPublic, FolderPublic } from "@/client"
import { EmbeddingStatusDot } from "@/components/Embeddings/EmbeddingStatusIcon"
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  useSidebar,
} from "@/components/ui/sidebar"
import { useCreateDocument, useRenameNode } from "@/hooks/useKbMutations"
import { canEditNamespace, useActiveNamespace } from "@/hooks/useNamespaces"
import { useTree, useTreeStore } from "@/hooks/useTree"
import { deriveEmbeddingState } from "@/lib/embeddingState"
import { cn } from "@/lib/utils"
import type { TreeIndex } from "@/queries/namespaces"
import { openDialog } from "@/stores/dialogs"
import { TreeInlineRename } from "./TreeInlineRename"
import {
  type ActionItem,
  type TreeNode,
  useTreeActions,
} from "./TreeNodeActions"

/* ------------------------------------------------------------------------- */
/* Shared menu rendering                                                     */
/* ------------------------------------------------------------------------- */

function DropdownItems({ items }: { items: ActionItem[] }) {
  return (
    <>
      {items.map((item) => (
        <Fragment key={item.key}>
          {item.separatorBefore && <DropdownMenuSeparator />}
          <DropdownMenuItem
            onClick={item.onSelect}
            variant={item.destructive ? "destructive" : "default"}
            data-testid={`tree-action-${item.key}`}
          >
            <item.icon className="size-4" />
            {item.label}
          </DropdownMenuItem>
        </Fragment>
      ))}
    </>
  )
}

function ContextItems({ items }: { items: ActionItem[] }) {
  return (
    <>
      {items.map((item) => (
        <Fragment key={item.key}>
          {item.separatorBefore && <ContextMenuSeparator />}
          <ContextMenuItem
            onClick={item.onSelect}
            variant={item.destructive ? "destructive" : "default"}
          >
            <item.icon className="size-4" />
            {item.label}
          </ContextMenuItem>
        </Fragment>
      ))}
    </>
  )
}

interface NodeShellProps {
  node: TreeNode
  namespaceId: string
  namespaceSlug: string
  canEdit: boolean
  children: React.ReactNode
  actionSlot?: (items: ActionItem[]) => React.ReactNode
}

/** Wraps a row in a right-click context menu and exposes the same actions for a hover button. */
function NodeShell({
  node,
  namespaceId,
  namespaceSlug,
  canEdit,
  children,
  actionSlot,
}: NodeShellProps) {
  const items = useTreeActions({ namespaceId, namespaceSlug, canEdit, node })
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <div className="group/row relative">
          {children}
          {actionSlot?.(items)}
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent className="w-52">
        <ContextItems items={items} />
      </ContextMenuContent>
    </ContextMenu>
  )
}

function HoverActions({
  items,
  label,
  sub,
}: {
  items: ActionItem[]
  label: string
  sub?: boolean
}) {
  if (items.length === 0) return null
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <SidebarMenuAction
          showOnHover
          aria-label={`Actions for ${label}`}
          className={cn(sub && "top-1 right-1")}
          data-testid="tree-node-actions"
        >
          <MoreHorizontal />
        </SidebarMenuAction>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="right" align="start" className="w-52">
        <DropdownItems items={items} />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/* ------------------------------------------------------------------------- */
/* Rows                                                                      */
/* ------------------------------------------------------------------------- */

interface RowContext {
  namespaceId: string
  namespaceSlug: string
  canEdit: boolean
  index: TreeIndex
  activeDocumentId: string | null
  activeFolderId: string | null
  depth: number
}

function DocumentRow({
  doc,
  ctx,
}: {
  doc: DocumentSummaryPublic
  ctx: RowContext
}) {
  const { isMobile, setOpenMobile } = useSidebar()
  const renamingId = useTreeStore((s) => s.renamingId)
  const setRenaming = useTreeStore((s) => s.setRenaming)
  const rename = useRenameNode()
  const isActive = ctx.activeDocumentId === doc.id
  const state = deriveEmbeddingState(doc)
  const isRenaming = renamingId === doc.id
  const Button = ctx.depth === 0 ? SidebarMenuButton : SidebarMenuSubButton
  const Item = ctx.depth === 0 ? SidebarMenuItem : SidebarMenuSubItem

  const label = isRenaming ? (
    <TreeInlineRename
      value={doc.title}
      onCancel={() => setRenaming(null)}
      onCommit={(name) => {
        setRenaming(null)
        rename.mutate({
          type: "document",
          id: doc.id,
          namespaceId: ctx.namespaceId,
          name,
        })
      }}
    />
  ) : (
    <span className="min-w-0 truncate">{doc.title}</span>
  )

  return (
    <Item role="treeitem" aria-selected={isActive} data-testid="tree-document">
      <NodeShell
        node={{ type: "document", document: doc }}
        namespaceId={ctx.namespaceId}
        namespaceSlug={ctx.namespaceSlug}
        canEdit={ctx.canEdit}
        actionSlot={(items) => (
          <HoverActions items={items} label={doc.title} sub={ctx.depth > 0} />
        )}
      >
        <Button
          asChild
          isActive={isActive}
          className={cn("pr-7", isRenaming && "bg-transparent!")}
          {...(ctx.depth === 0 ? { tooltip: doc.title } : {})}
        >
          <Link
            to="/s/$namespaceSlug/d/$documentId"
            params={{ namespaceSlug: ctx.namespaceSlug, documentId: doc.id }}
            search={{ mode: "view" } as never}
            onClick={(e) => {
              if (isRenaming) e.preventDefault()
              else if (isMobile) setOpenMobile(false)
            }}
            onDoubleClick={(e) => {
              if (ctx.canEdit) {
                e.preventDefault()
                setRenaming(doc.id)
              }
            }}
          >
            <FileText className="text-muted-foreground" />
            {label}
            <EmbeddingStatusDot state={state} className="ml-auto" />
          </Link>
        </Button>
      </NodeShell>
    </Item>
  )
}

function FolderRow({ folder, ctx }: { folder: FolderPublic; ctx: RowContext }) {
  const expanded = useTreeStore((s) => s.isExpanded(ctx.namespaceId, folder.id))
  const toggle = useTreeStore((s) => s.toggle)
  const renamingId = useTreeStore((s) => s.renamingId)
  const setRenaming = useTreeStore((s) => s.setRenaming)
  const rename = useRenameNode()
  const navigate = useNavigate()
  const { isMobile, setOpenMobile } = useSidebar()
  const isActive = ctx.activeFolderId === folder.id
  const isRenaming = renamingId === folder.id
  const childFolders = ctx.index.childrenOf(folder.id)
  const childDocs = ctx.index.docsOf(folder.id)
  const hasChildren = childFolders.length + childDocs.length > 0
  const Button = ctx.depth === 0 ? SidebarMenuButton : SidebarMenuSubButton
  const Item = ctx.depth === 0 ? SidebarMenuItem : SidebarMenuSubItem
  const FolderIcon = expanded ? FolderOpen : Folder

  const openFolder = () => {
    navigate({
      to: "/s/$namespaceSlug/f/$folderId",
      params: { namespaceSlug: ctx.namespaceSlug, folderId: folder.id },
    })
    if (isMobile) setOpenMobile(false)
  }

  const label = isRenaming ? (
    <TreeInlineRename
      value={folder.name}
      onCancel={() => setRenaming(null)}
      onCommit={(name) => {
        setRenaming(null)
        rename.mutate({
          type: "folder",
          id: folder.id,
          namespaceId: ctx.namespaceId,
          name,
        })
      }}
    />
  ) : (
    <span className="min-w-0 truncate">{folder.name}</span>
  )

  return (
    <Item
      role="treeitem"
      aria-expanded={expanded}
      aria-selected={isActive}
      data-testid="tree-folder"
    >
      <NodeShell
        node={{ type: "folder", folder }}
        namespaceId={ctx.namespaceId}
        namespaceSlug={ctx.namespaceSlug}
        canEdit={ctx.canEdit}
        actionSlot={(items) => (
          <HoverActions items={items} label={folder.name} sub={ctx.depth > 0} />
        )}
      >
        <Button
          isActive={isActive}
          className={cn("pr-7", isRenaming && "bg-transparent!")}
          onClick={() => {
            if (isRenaming) return
            if (!expanded) toggle(ctx.namespaceId, folder.id)
            openFolder()
          }}
          onDoubleClick={() => ctx.canEdit && setRenaming(folder.id)}
          {...(ctx.depth === 0 ? { tooltip: folder.name } : {})}
        >
          <span
            aria-hidden="true"
            className="-ml-1 flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-sidebar-accent hover:text-foreground"
            onClick={(e) => {
              e.stopPropagation()
              toggle(ctx.namespaceId, folder.id)
            }}
          >
            <ChevronRight
              className={cn(
                "size-3.5 transition-transform",
                expanded && "rotate-90",
                !hasChildren && "opacity-30",
              )}
            />
          </span>
          <FolderIcon className="text-muted-foreground" />
          {label}
        </Button>
      </NodeShell>
      {expanded && (
        <SidebarMenuSub role="group" className="mr-0 pr-0">
          {childFolders.map((child) => (
            <FolderRow
              key={child.id}
              folder={child}
              ctx={{ ...ctx, depth: ctx.depth + 1 }}
            />
          ))}
          {childDocs.map((doc) => (
            <DocumentRow
              key={doc.id}
              doc={doc}
              ctx={{ ...ctx, depth: ctx.depth + 1 }}
            />
          ))}
          {!hasChildren && (
            <li className="px-2 py-1 text-xs text-muted-foreground/70">
              Empty folder
            </li>
          )}
        </SidebarMenuSub>
      )}
    </Item>
  )
}

/* ------------------------------------------------------------------------- */
/* Tree                                                                      */
/* ------------------------------------------------------------------------- */

function TreeSkeleton() {
  return (
    <SidebarMenu>
      {[0, 1, 2, 3, 4].map((i) => (
        <SidebarMenuItem key={i}>
          <SidebarMenuSkeleton showIcon />
        </SidebarMenuItem>
      ))}
    </SidebarMenu>
  )
}

export function SpaceTree() {
  const { active } = useActiveNamespace()
  const params = useParams({ strict: false }) as {
    documentId?: string
    folderId?: string
  }
  const { data: index, isPending, isError } = useTree(active?.id)
  const expandMany = useTreeStore((s) => s.expandMany)
  const createDocument = useCreateDocument()
  const canEdit = canEditNamespace(active)

  // Keep the ancestors of the current page/folder open.
  const activeFolderId = useMemo(() => {
    if (!index) return null
    if (params.folderId) return params.folderId
    if (params.documentId) {
      return index.documentsById.get(params.documentId)?.folder_id ?? null
    }
    return null
  }, [index, params.folderId, params.documentId])

  useEffect(() => {
    if (!index || !active || !activeFolderId) return
    const ids = index.pathTo(activeFolderId).map((f) => f.id)
    if (ids.length) expandMany(active.id, ids)
  }, [index, active, activeFolderId, expandMany])

  if (!active) {
    return (
      <SidebarGroup className="group-data-[collapsible=icon]:hidden">
        <SidebarGroupLabel>Pages</SidebarGroupLabel>
        <SidebarGroupContent>
          <div className="mx-2 flex flex-col items-center gap-2 rounded-md border border-dashed px-3 py-6 text-center">
            <FileText className="size-5 text-muted-foreground" />
            <p className="text-xs text-muted-foreground">
              Create a space to start adding pages.
            </p>
          </div>
        </SidebarGroupContent>
      </SidebarGroup>
    )
  }

  const rootCtx: RowContext | null = index
    ? {
        namespaceId: active.id,
        namespaceSlug: active.slug,
        canEdit,
        index,
        activeDocumentId: params.documentId ?? null,
        activeFolderId: params.folderId ?? null,
        depth: 0,
      }
    : null

  const rootFolders = index?.childrenOf(null) ?? []
  const rootDocs = index?.docsOf(null) ?? []
  const isEmpty = index && rootFolders.length === 0 && rootDocs.length === 0

  return (
    <SidebarGroup className="group-data-[collapsible=icon]:hidden">
      <SidebarGroupLabel asChild>
        <Link
          to="/s/$namespaceSlug"
          params={{ namespaceSlug: active.slug }}
          className="hover:text-foreground"
        >
          Pages in {active.name}
        </Link>
      </SidebarGroupLabel>
      {canEdit && (
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild>
            <SidebarGroupAction title="Add" data-testid="tree-root-add">
              <Plus />
              <span className="sr-only">Add</span>
            </SidebarGroupAction>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="right" align="start" className="w-48">
            <DropdownMenuItem
              onClick={() =>
                createDocument.mutate({
                  namespaceId: active.id,
                  namespaceSlug: active.slug,
                  folderId: null,
                })
              }
              data-testid="tree-root-new-page"
            >
              <FilePlus2 className="size-4" />
              New page
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() =>
                openDialog({
                  kind: "newFolder",
                  namespaceId: active.id,
                  namespaceSlug: active.slug,
                  parentId: null,
                })
              }
              data-testid="tree-root-new-folder"
            >
              <Folder className="size-4" />
              New folder
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      <SidebarGroupContent>
        {isPending && <TreeSkeleton />}
        {isError && (
          <p className="px-2 text-xs text-destructive">Couldn't load pages.</p>
        )}
        {rootCtx && isEmpty && (
          <div className="mx-2 flex flex-col items-center gap-2 rounded-md border border-dashed px-3 py-5 text-center">
            <FileText className="size-5 text-muted-foreground" />
            <p className="text-xs text-muted-foreground">No pages yet.</p>
            {canEdit && (
              <button
                type="button"
                className="text-xs font-medium text-primary hover:underline"
                onClick={() =>
                  createDocument.mutate({
                    namespaceId: active.id,
                    namespaceSlug: active.slug,
                    folderId: null,
                  })
                }
              >
                Create your first page
              </button>
            )}
          </div>
        )}
        {rootCtx && !isEmpty && (
          <SidebarMenu role="tree" aria-label={`Pages in ${active.name}`}>
            {rootFolders.map((folder) => (
              <FolderRow key={folder.id} folder={folder} ctx={rootCtx} />
            ))}
            {rootDocs.map((doc) => (
              <DocumentRow key={doc.id} doc={doc} ctx={rootCtx} />
            ))}
          </SidebarMenu>
        )}
      </SidebarGroupContent>
    </SidebarGroup>
  )
}
