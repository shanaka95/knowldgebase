import { queryOptions } from "@tanstack/react-query"

import { DocumentsService, PublicService, UsersService } from "@/client"
import { queryKeys } from "@/lib/queryKeys"

export function documentSharesQuery(documentId: string) {
  return queryOptions({
    queryKey: queryKeys.documents.shares(documentId),
    queryFn: async () =>
      (
        await DocumentsService.readDocumentShares({
          path: { document_id: documentId },
        })
      ).data,
  })
}

export function documentInvitationsQuery(documentId: string) {
  return queryOptions({
    queryKey: queryKeys.documents.invitations(documentId),
    queryFn: async () =>
      (
        await DocumentsService.readDocumentInvitations({
          path: { document_id: documentId },
        })
      ).data,
  })
}

/**
 * Whether one exact address already has an account.
 *
 * The backend answers exact addresses only and 422s on anything else, so only
 * call this with a value that already parses as a complete address. The answer
 * barely changes, so it is cached for the life of the dialog rather than asked
 * again every time the chip list re-renders.
 */
export function userLookupQuery(email: string) {
  return queryOptions({
    queryKey: queryKeys.userLookup(email),
    queryFn: async () =>
      (await UsersService.lookupUser({ query: { email } })).data,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

/** A page shared by link. Deliberately usable with no session at all. */
export function publicDocumentQuery(identifier: string) {
  return queryOptions({
    queryKey: queryKeys.publicDocument(identifier),
    queryFn: async () =>
      (
        await PublicService.readPublicDocument({
          path: { identifier },
        })
      ).data,
    retry: false,
  })
}

/** What an invitation link is for. Also unauthenticated. */
export function invitationPreviewQuery(token: string) {
  return queryOptions({
    queryKey: queryKeys.invitationPreview(token),
    queryFn: async () =>
      (await PublicService.readInvitation({ path: { token } })).data,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  })
}
