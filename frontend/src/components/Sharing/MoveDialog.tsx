import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import { useMoveNode } from "@/hooks/useKbMutations"
import { canEditNamespace, useNamespaces } from "@/hooks/useNamespaces"
import { treeQuery } from "@/queries/namespaces"
import type { DialogTarget } from "@/stores/dialogs"
import { DestinationPicker } from "./DestinationPicker"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  target: Extract<DialogTarget, { type: "folder" | "document" }>
}

export function MoveDialog({ open, onOpenChange, target }: Props) {
  const { data: namespaces } = useNamespaces()
  const move = useMoveNode()
  const navigate = useNavigate()
  const isFolder = target.type === "folder"
  const currentParent =
    target.type === "folder" ? target.parentId : target.folderId

  const [namespaceId, setNamespaceId] = useState(target.namespaceId)
  const [folderId, setFolderId] = useState<string | null>(currentParent)

  const editable = useMemo(
    () => (namespaces?.data ?? []).filter(canEditNamespace),
    [namespaces],
  )
  // folders can only move inside their own space
  const spaceOptions = isFolder
    ? editable.filter((n) => n.id === target.namespaceId)
    : editable

  const { data: index } = useQuery(treeQuery(namespaceId))

  const disabled = useMemo(() => {
    if (!index || !isFolder) return new Set<string>()
    return index.descendantIds(target.id)
  }, [index, isFolder, target.id])

  const unchanged =
    namespaceId === target.namespaceId &&
    (folderId ?? null) === (currentParent ?? null)

  const targetNamespace = spaceOptions.find((n) => n.id === namespaceId)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" data-testid="move-dialog">
        <DialogHeader>
          <DialogTitle>
            Move “{target.type === "folder" ? target.name : target.title}”
          </DialogTitle>
          <DialogDescription>
            {isFolder
              ? "Choose a new parent folder inside this space."
              : "Choose a space and folder for this page."}
          </DialogDescription>
        </DialogHeader>
        <DestinationPicker
          spaces={spaceOptions}
          namespaceId={namespaceId}
          onNamespaceChange={(id) => {
            setNamespaceId(id)
            setFolderId(null)
          }}
          folderId={folderId}
          onFolderChange={setFolderId}
          disabledFolderIds={disabled}
          lockSpace={isFolder}
        />
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={move.isPending}
          >
            Cancel
          </Button>
          <LoadingButton
            disabled={unchanged}
            loading={move.isPending}
            data-testid="move-submit"
            onClick={() =>
              move.mutate(
                {
                  type: target.type,
                  id: target.id,
                  sourceNamespaceId: target.namespaceId,
                  targetNamespaceId: namespaceId,
                  targetFolderId: folderId,
                },
                {
                  onSuccess: () => {
                    onOpenChange(false)
                    if (
                      target.type === "document" &&
                      namespaceId !== target.namespaceId &&
                      targetNamespace &&
                      window.location.pathname.includes(target.id)
                    ) {
                      navigate({
                        to: "/s/$namespaceSlug/d/$documentId",
                        params: {
                          namespaceSlug: targetNamespace.slug,
                          documentId: target.id,
                        },
                        search: { mode: "view" } as never,
                      })
                    }
                  },
                },
              )
            }
          >
            Move here
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
