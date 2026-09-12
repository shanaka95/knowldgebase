import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useState } from "react"

import { NamespacesService } from "@/client"
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { LAST_NAMESPACE_KEY } from "@/hooks/useNamespaces"
import { queryKeys } from "@/lib/queryKeys"
import { handleError } from "@/utils"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  namespace: { id: string; name: string; slug: string }
}

export function DeleteNamespaceDialog({
  open,
  onOpenChange,
  namespace,
}: Props) {
  const [confirm, setConfirm] = useState("")
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const mutation = useMutation({
    mutationFn: () =>
      NamespacesService.deleteNamespace({
        path: { namespace_id: namespace.id },
      }),
    onSuccess: () => {
      showSuccessToast(`Space “${namespace.name}” deleted`)
      try {
        if (localStorage.getItem(LAST_NAMESPACE_KEY) === namespace.slug) {
          localStorage.removeItem(LAST_NAMESPACE_KEY)
        }
      } catch {
        /* ignore */
      }
      queryClient.invalidateQueries({ queryKey: queryKeys.namespaces.all })
      queryClient.invalidateQueries({ queryKey: queryKeys.documents.all })
      queryClient.invalidateQueries({ queryKey: queryKeys.shared })
      onOpenChange(false)
      navigate({ to: "/" })
    },
    onError: handleError.bind(showErrorToast),
  })

  const matches = confirm.trim() === namespace.name

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent data-testid="delete-namespace-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>Delete “{namespace.name}”?</AlertDialogTitle>
          <AlertDialogDescription>
            Every folder, page, attachment and share in this space will be
            permanently deleted, and its embeddings removed from the index. This
            cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor="confirm-namespace-name">
            Type <span className="font-semibold">{namespace.name}</span> to
            confirm
          </Label>
          <Input
            id="confirm-namespace-name"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="off"
            data-testid="delete-namespace-confirm"
          />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={mutation.isPending}>
            Cancel
          </AlertDialogCancel>
          <LoadingButton
            variant="destructive"
            disabled={!matches}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
            data-testid="delete-namespace-submit"
          >
            Delete space
          </LoadingButton>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
