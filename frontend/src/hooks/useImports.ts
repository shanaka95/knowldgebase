import { useMutation, useQueryClient } from "@tanstack/react-query"

import { type ImportJobPublic, ImportsService } from "@/client"
import useCustomToast from "@/hooks/useCustomToast"
import { invalidateNamespaceViews } from "@/hooks/useKbMutations"
import { importKeys } from "@/queries/imports"
import { handleError } from "@/utils"

export interface CreateImportInput {
  files: File[]
  namespaceId: string
  folderId: string | null
  title?: string | null
  prompt?: string | null
  /** Something to say about the page, kept as its first note. */
  note?: string | null
  /**
   * Make one page out of every file instead of one page each. For a document
   * that arrived as a set of scans this is the difference between a report and
   * a folder of fragments.
   */
  combine?: boolean
}

export function useCreateImport() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  return useMutation({
    mutationFn: async (
      input: CreateImportInput,
    ): Promise<ImportJobPublic[]> => {
      const res = await ImportsService.createImports({
        body: {
          files: input.files,
          namespace_id: input.namespaceId,
          folder_id: input.folderId,
          title: input.title?.trim() || null,
          prompt: input.prompt?.trim() || null,
          note: input.note?.trim() || null,
          combine: input.combine ?? false,
        },
      })
      return res.data.data
    },
    onSuccess: (jobs) => {
      const first = jobs[0]
      if (!first) return
      if (jobs.length > 1) {
        showSuccessToast(
          `${jobs.length} files queued. Each becomes a page once parsing finishes.`,
        )
      } else if ((first.file_count ?? 1) > 1) {
        showSuccessToast(
          `${first.file_count} files queued. They become one page once parsing finishes.`,
        )
      } else {
        showSuccessToast(
          `“${first.filename}” is queued. It becomes a page once parsing finishes.`,
        )
      }
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
