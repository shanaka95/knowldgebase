import { useNavigate, useParams } from "@tanstack/react-router"

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import { useDeleteNode } from "@/hooks/useKbMutations"
import { useTree } from "@/hooks/useTree"
import type { DialogTarget } from "@/stores/dialogs"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  target: Extract<DialogTarget, { type: "folder" | "document" }>
}

export function DeleteDialog({ open, onOpenChange, target }: Props) {
  const remove = useDeleteNode()
  const navigate = useNavigate()
  const params = useParams({ strict: false }) as {
    documentId?: string
    folderId?: string
  }
  const { data: index } = useTree(target.namespaceId)

  const isFolder = target.type === "folder"
  const name = isFolder ? target.name : target.title
  let nested = 0
  if (isFolder && index) {
    const ids = index.descendantIds(target.id)
    nested =
      ids.size -
      1 +
      index.raw.documents.filter((d) => d.folder_id && ids.has(d.folder_id))
        .length
  }

  const currentlyViewing =
    (target.type === "document" && params.documentId === target.id) ||
    (isFolder &&
      (params.folderId === target.id ||
        (params.documentId &&
          index?.documentsById.get(params.documentId)?.folder_id &&
          index
            .descendantIds(target.id)
            .has(
              index.documentsById.get(params.documentId)?.folder_id as string,
            ))))

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent data-testid="delete-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>
            Delete {isFolder ? "folder" : "page"} “{name}”?
          </AlertDialogTitle>
          <AlertDialogDescription>
            {isFolder
              ? nested > 0
                ? `This folder contains ${nested} nested item${
                    nested === 1 ? "" : "s"
                  }. Everything inside will be deleted too.`
                : "The folder is empty."
              : "The page, its attachments and its embeddings will be removed."}{" "}
            This cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={remove.isPending}>
            Cancel
          </AlertDialogCancel>
          <LoadingButton
            variant="destructive"
            loading={remove.isPending}
            data-testid="delete-dialog-submit"
            onClick={() =>
              remove.mutate(
                {
                  type: target.type,
                  id: target.id,
                  namespaceId: target.namespaceId,
                },
                {
                  onSuccess: () => {
                    onOpenChange(false)
                    if (currentlyViewing) {
                      navigate({
                        to: "/s/$namespaceSlug",
                        params: { namespaceSlug: target.namespaceSlug },
                      })
                    }
                  },
                },
              )
            }
          >
            Delete
          </LoadingButton>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
