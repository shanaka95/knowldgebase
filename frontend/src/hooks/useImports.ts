import { useMutation, useQueryClient } from "@tanstack/react-query"

import { type ImportJobPublic, ImportsService } from "@/client"
import useCustomToast from "@/hooks/useCustomToast"
import { invalidateNamespaceViews } from "@/hooks/useKbMutations"
import { importKeys } from "@/queries/imports"
import { handleError } from "@/utils"

export interface CreateImportInput {
  file: File
  namespaceId: string
  folderId: string | null
  title?: string | null
  prompt?: string | null
}

export function useCreateImport() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  return useMutation({
    mutationFn: async (input: CreateImportInput): Promise<ImportJobPublic> => {
      const res = await ImportsService.createImport({
        body: {
          file: input.file,
          namespace_id: input.namespaceId,
          folder_id: input.folderId,
          title: input.title?.trim() || null,
          prompt: input.prompt?.trim() || null,
        },
      })
      return res.data
    },
    onSuccess: (job) => {
      showSuccessToast(
        `“${job.filename}” is queued. It becomes a page once parsing finishes.`,
      )
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: importKeys.all })
    },
  })
}

export function useRetryImport() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  return useMutation({
    mutationFn: async (importId: string) =>
      (await ImportsService.retryImport({ path: { import_id: importId } }))
        .data,
    onSuccess: () => showSuccessToast("Import queued again."),
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: importKeys.all })
    },
  })
}

export function useCancelImport() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  return useMutation({
    mutationFn: async (importId: string) =>
      (await ImportsService.cancelImport({ path: { import_id: importId } }))
        .data,
    onSuccess: () => showSuccessToast("Import cancelled."),
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: importKeys.all })
    },
  })
}

export function useDeleteImport() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  return useMutation({
    mutationFn: async (job: ImportJobPublic) => {
      await ImportsService.deleteImport({ path: { import_id: job.id } })
      return job
    },
    onSuccess: (job) => {
      showSuccessToast("Import removed.")
      // a finished import created a page, so the tree and recents may change
      if (job.document_id)
        invalidateNamespaceViews(queryClient, job.namespace_id)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: importKeys.all })
    },
  })
}
