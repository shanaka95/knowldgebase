import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"
import { useState } from "react"

import { type ApiKeyPublic, ApiKeysService } from "@/client"
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { queryKeys } from "@/lib/queryKeys"
import { handleError } from "@/utils"

export function RevokeApiKeyDialog({ apiKey }: { apiKey: ApiKeyPublic }) {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const mutation = useMutation({
    mutationFn: () =>
      ApiKeysService.revokeApiKey({ path: { key_id: apiKey.id } }),
    onSuccess: () => {
      showSuccessToast(`Key “${apiKey.name}” revoked`)
      queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys })
      setOpen(false)
    },
    onError: handleError.bind(showErrorToast),
  })
  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Revoke ${apiKey.name}`}
          data-testid="api-key-revoke"
        >
          <Trash2 className="size-4 text-muted-foreground" />
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Revoke “{apiKey.name}”?</AlertDialogTitle>
          <AlertDialogDescription>
            Any app using this key will immediately lose access. This cannot be
            undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={mutation.isPending}>
            Cancel
          </AlertDialogCancel>
          <LoadingButton
            variant="destructive"
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
            data-testid="api-key-revoke-confirm"
          >
            Revoke key
          </LoadingButton>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
