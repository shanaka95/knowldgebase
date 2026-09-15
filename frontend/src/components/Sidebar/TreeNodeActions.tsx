import { useNavigate } from "@tanstack/react-router"
import {
  FilePlus2,
  FolderPlus,
  Link2,
  MoveRight,
  Pencil,
  Share2,
  Trash2,
  Upload,
} from "lucide-react"
import type { ComponentType } from "react"

import type { DocumentSummaryPublic, FolderPublic } from "@/client"
import useCustomToast from "@/hooks/useCustomToast"
import { useCreateDocument } from "@/hooks/useKbMutations"
import { useTreeStore } from "@/hooks/useTree"
import { absoluteUrl, links } from "@/lib/links"
import { type DialogTarget, openDialog } from "@/stores/dialogs"

export type TreeNode =
  | { type: "folder"; folder: FolderPublic }
  | { type: "document"; document: DocumentSummaryPublic }
  | { type: "root" }

export interface ActionItem {
  key: string
  label: string
  icon: ComponentType<{ className?: string }>
  onSelect: () => void
  destructive?: boolean
  separatorBefore?: boolean
}

interface UseTreeActionsArgs {
  namespaceId: string
  namespaceSlug: string
  canEdit: boolean
  node: TreeNode
}

/** Builds the shared action list used by both the hover "…" menu and the context menu. */
export function useTreeActions({
  namespaceId,
  namespaceSlug,
  canEdit,
  node,
}: UseTreeActionsArgs): ActionItem[] {
  const createDocument = useCreateDocument()
  const setRenaming = useTreeStore((s) => s.setRenaming)
  const { showSuccessToast } = useCustomToast()
  const navigate = useNavigate()

  const folderId =
    node.type === "folder"
      ? node.folder.id
      : node.type === "document"
        ? (node.document.folder_id ?? null)
        : null

  const target: DialogTarget | null =
    node.type === "folder"
      ? {
          type: "folder",
          id: node.folder.id,
          namespaceId,
          namespaceSlug,
          name: node.folder.name,
          parentId: node.folder.parent_id ?? null,
        }
      : node.type === "document"
        ? {
            type: "document",
            id: node.document.id,
            namespaceId,
            namespaceSlug,
            title: node.document.title,
            folderId: node.document.folder_id ?? null,
          }
        : null

  const items: ActionItem[] = []

  if (canEdit) {
    items.push({
      key: "new-page",
      label: "New page",
      icon: FilePlus2,
      onSelect: () =>
        createDocument.mutate({ namespaceId, namespaceSlug, folderId }),
    })
    if (node.type !== "document") {
      items.push({
        key: "new-folder",
        label: "New folder",
        icon: FolderPlus,
        onSelect: () =>
          openDialog({
            kind: "newFolder",
            namespaceId,
            namespaceSlug,
            parentId: folderId,
          }),
      })
      // Right where the folder is: the upload dialog opens with this space and
      // folder already filled in.
      items.push({
        key: "upload-here",
        label: "Upload a document",
        icon: Upload,
        onSelect: () =>
          openDialog({ kind: "import", namespaceId, namespaceSlug, folderId }),
      })
    }
  }

  if (node.type !== "root") {
    items.push({
      key: "open",
      label: node.type === "folder" ? "Open folder" : "Open page",
      icon: Link2,
      separatorBefore: canEdit,
      onSelect: () =>
        node.type === "folder"
          ? navigate({
              to: "/s/$namespaceSlug/f/$folderId",
              params: { namespaceSlug, folderId: node.folder.id },
            })
          : navigate({
              to: "/s/$namespaceSlug/d/$documentId",
              params: { namespaceSlug, documentId: node.document.id },
              search: { mode: "view" } as never,
            }),
    })
    items.push({
      key: "copy-link",
      label: "Copy link",
      icon: Link2,
      onSelect: async () => {
        const path =
          node.type === "folder"
            ? links.folder(namespaceSlug, node.folder.id)
            : links.document(namespaceSlug, node.document.id)
        try {
          await navigator.clipboard.writeText(absoluteUrl(path))
          showSuccessToast("Link copied to clipboard")
        } catch {
          /* clipboard unavailable */
        }
      },
    })
  }

  if (canEdit && target) {
    items.push({
      key: "rename",
      label: "Rename",
      icon: Pencil,
      separatorBefore: true,
      onSelect: () => setRenaming(target.id),
    })
    items.push({
      key: "move",
      label: "Move to…",
      icon: MoveRight,
      onSelect: () => openDialog({ kind: "move", target }),
    })
    if (target.type === "document") {
      items.push({
        key: "share",
        label: "Share",
        icon: Share2,
        onSelect: () => openDialog({ kind: "share", target }),
      })
    }
    items.push({
      key: "delete",
      label: "Delete",
      icon: Trash2,
      destructive: true,
      separatorBefore: true,
      onSelect: () => openDialog({ kind: "delete", target }),
    })
  }

  return items
}
