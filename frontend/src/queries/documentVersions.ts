import {
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query"

import {
  type DocumentLanguages,
  DocumentsService,
  type DocumentVersionPublic,
  type DocumentVersionsPublic,
  type TranslationPublic,
} from "@/client"
import { queryKeys } from "@/lib/queryKeys"

/** Every version of a page: titles and sizes, not content. */
export function documentVersionsQuery(documentId: string) {
  return queryOptions({
    queryKey: queryKeys.documents.versions(documentId),
    queryFn: async (): Promise<DocumentVersionsPublic> =>
      (
        await DocumentsService.readDocumentVersions({
          path: { document_id: documentId },
        })
      ).data,
    staleTime: 30_000,
  })
}

/**
 * One version with its content.
 *
 * Cached forever: a version that already exists cannot change - that is what
 * makes it a version - so re-reading one the reader has already opened is
 * wasted work.
 */
export function documentVersionQuery(documentId: string, version: number) {
  return queryOptions({
    queryKey: queryKeys.documents.version(documentId, version),
    queryFn: async (): Promise<DocumentVersionPublic> =>
      (
        await DocumentsService.readDocumentVersion({
          path: { document_id: documentId, version },
        })
      ).data,
    staleTime: Number.POSITIVE_INFINITY,
  })
}

/** The page's own language, what is already translated, and what is on offer. */
export function documentLanguagesQuery(documentId: string) {
  return queryOptions({
    queryKey: queryKeys.documents.languages(documentId),
    queryFn: async (): Promise<DocumentLanguages> =>
      (
        await DocumentsService.readDocumentLanguages({
          path: { document_id: documentId },
        })
      ).data,
    staleTime: 30_000,
  })
}

/**
 * Ask for the page in another language.
 *
 * Only the language travels: the page is read on the server. A translation
 * that already exists for this version comes straight back, so this is cheap
 * for everybody after the first reader.
 */
export function useTranslateDocument(documentId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (language: string): Promise<TranslationPublic> =>
      (
        await DocumentsService.translateDocument({
          path: { document_id: documentId },
          body: { language },
        })
      ).data,
    onSuccess: (translation) => {
      // Keep it, keyed by the version it was written for: switching back to a
      // language read a moment ago should not translate it again.
      queryClient.setQueryData(
        queryKeys.documents.translation(
          documentId,
          translation.doc_version,
          translation.language,
        ),
        translation,
      )
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documents.languages(documentId),
      })
    },
  })
}

/** A translation already fetched in this session, if there is one. */
export function translationKey(
  documentId: string,
  version: number,
  language: string,
) {
  return queryKeys.documents.translation(documentId, version, language)
}
