import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useMemo, useState } from "react"
import { toast } from "sonner"

import { DocumentsService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { invalidateNamespaceViews } from "@/hooks/useKbMutations"
import { canEditNamespace, useNamespaces } from "@/hooks/useNamespaces"
import type { DialogTarget } from "@/stores/dialogs"
import { handleError } from "@/utils"
import { DestinationPicker } from "./DestinationPicker"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  target: Extract<DialogTarget, { type: "document" }>
}

/**
 * Keeping your own copy of a page — including one somebody else shared with
 * you. The copy is a separate page from the moment it exists, so it goes
 * wherever you can write, not wherever the original lives.
 */
export function CopyDialog({ open, onOpenChange, target }: Props) {
  const { data: namespaces } = useNamespaces()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()

  const editable = useMemo(
    () => (namespaces?.data ?? []).filter(canEditNamespace),
    [namespaces],
  )
  // The original's space is only a sensible default when it is writable; a page
  // shared from someone else's space is not.
  const initialNamespace =
    editable.find((n) => n.id === target.namespaceId)?.id ?? editable[0]?.id

  // Held as "nothing chosen yet" rather than seeded from `initialNamespace`,
  // which is undefined until the space list arrives.
  const [chosen, setChosen] = useState<{
    namespaceId: string
    folderId: string | null
  } | null>(null)
  const namespaceId = chosen?.namespaceId ?? initialNamespace
  const folderId = chosen
    ? chosen.folderId
    : namespaceId === target.namespaceId
      ? target.folderId
      : null
  const [title, setTitle] = useState(`${target.title} (copy)`)

  const destination = editable.find((n) => n.id === namespaceId)

  const clone = useMutation({
    mutationFn: async () => {
      if (!namespaceId) throw new Error("Choose a space for the copy.")
      return (
        await DocumentsService.cloneDocument({
          path: { document_id: target.id },
          body: {
            namespace_id: namespaceId,
            folder_id: folderId,
            title: title.trim() || null,
          },
        })
      ).data
    },
    onSuccess: (copy) => {
      invalidateNamespaceViews(queryClient, copy.namespace_id)
      onOpenChange(false)
      const slug = copy.namespace_slug ?? destination?.slug
      if (slug) {
        navigate({
          to: "/s/$namespaceSlug/d/$documentId",
          params: { namespaceSlug: slug, documentId: copy.id },
          search: { mode: "view" } as never,
        })
      }
      // Said after the copy exists rather than before, because "private until
      // you share it" is the one thing somebody could get wrong about it.
      toast.success("Copy created", {
        description: "It is private until you share it.",
      })
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" data-testid="copy-dialog">
        <DialogHeader>
          <DialogTitle>Make a copy of “{target.title}”</DialogTitle>
          <DialogDescription>
            The copy is yours. Editing it does not touch the original, and
            nobody else can see it until you share it.
          </DialogDescription>
        </DialogHeader>

        {editable.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            You need edit access to at least one space before you can keep a
            copy.
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="copy-title">Title</Label>
              <Input
                id="copy-title"
                value={title}
                maxLength={300}
                onChange={(e) => setTitle(e.target.value)}
                data-testid="copy-title"
              />
            </div>
            {namespaceId && (
              <DestinationPicker
                spaces={editable}
                namespaceId={namespaceId}
                onNamespaceChange={(id) =>
                  setChosen({ namespaceId: id, folderId: null })
                }
                folderId={folderId}
                onFolderChange={(id) =>
                  setChosen({ namespaceId, folderId: id })
                }
              />
            )}
          </div>
        )}

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={clone.isPending}
          >
            Cancel
          </Button>
          <LoadingButton
            loading={clone.isPending}
            disabled={!namespaceId}
            onClick={() => clone.mutate()}
            data-testid="copy-submit"
          >
            Make a copy
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
