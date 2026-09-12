import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"

import {
  type DocumentPublic,
  DocumentsService,
  type DocumentUpdate,
  type EmbeddingJobPublic,
} from "@/client"
import useCustomToast from "@/hooks/useCustomToast"
import { queryKeys } from "@/lib/queryKeys"
import { handleError } from "@/utils"

export function useDocumentMutations(document: {
  id: string
  namespace_id: string
  namespace_slug?: string | null
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const invalidateAround = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.namespaces.tree(document.namespace_id),
    })
    void queryClient.invalidateQueries({
      queryKey: queryKeys.documents.recent(),
    })
    void queryClient.invalidateQueries({ queryKey: queryKeys.embeddingSummary })
  }

  const update = useMutation({
    mutationFn: async (body: DocumentUpdate): Promise<DocumentPublic> =>
      (
        await DocumentsService.updateDocument({
          path: { document_id: document.id },
          body,
        })
      ).data,
    onSuccess: (fresh) => {
      queryClient.setQueryData(queryKeys.documents.detail(document.id), fresh)
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documents.embeddings(document.id),
      })
      invalidateAround()
    },
  })

  const regenerate = useMutation({
    mutationFn: async (): Promise<EmbeddingJobPublic> =>
      (
        await DocumentsService.regenerateDocumentEmbeddings({
          path: { document_id: document.id },
        })
      ).data,
    onMutate: () => {
      // optimistic: show "Queued" immediately
      queryClient.setQueryData<DocumentPublic>(
        queryKeys.documents.detail(document.id),
        (prev) =>
          prev
            ? { ...prev, embedding_status: "pending", embedding_error: null }
            : prev,
      )
    },
    onSuccess: () => {
      showSuccessToast("Re-indexing queued")
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documents.embeddings(document.id),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documents.detail(document.id),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.embeddingSummary,
      })
    },
  })

  const remove = useMutation({
    mutationFn: async () =>
      (
        await DocumentsService.deleteDocument({
          path: { document_id: document.id },
        })
      ).data,
    onSuccess: () => {
      showSuccessToast("Page deleted")
      queryClient.removeQueries({
        queryKey: queryKeys.documents.detail(document.id),
      })
      invalidateAround()
      if (document.namespace_slug) {
        void navigate({
          to: "/s/$namespaceSlug",
          params: { namespaceSlug: document.namespace_slug },
        })
      } else {
        void navigate({ to: "/" })
      }
    },
    onError: handleError.bind(showErrorToast),
  })

  return { update, regenerate, remove }
}
