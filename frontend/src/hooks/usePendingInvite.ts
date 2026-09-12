import { useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useEffect } from "react"

import { documentQuery } from "@/queries/documents"

const KEY = "kb:pendingInviteDocumentId"

/**
 * Remember the page an invitation was for, so the sign-up → confirm → sign-in
 * detour can end where it started. Session storage because it is one journey in
 * one tab, and because a stale id left behind for weeks would be worse than
 * losing it when the tab closes.
 */
export function rememberInvitedDocument(documentId: string) {
  try {
    sessionStorage.setItem(KEY, documentId)
  } catch {
    /* private browsing, or storage disabled — the landing page still works */
  }
}

function takeInvitedDocument(): string | null {
  try {
    const value = sessionStorage.getItem(KEY)
    if (value) sessionStorage.removeItem(KEY)
    return value
  } catch {
    return null
  }
}

/**
 * Once the invited person is signed in, take them to the page they were sent.
 * Mounted in the authenticated layout, so it fires wherever they land.
 */
export function usePendingInviteRedirect() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  useEffect(() => {
    const documentId = takeInvitedDocument()
    if (!documentId) return
    let cancelled = false
    queryClient
      .fetchQuery(documentQuery(documentId))
      .then((document) => {
        if (cancelled || !document.namespace_slug) return
        navigate({
          to: "/s/$namespaceSlug/d/$documentId",
          params: {
            namespaceSlug: document.namespace_slug,
            documentId: document.id,
          },
          search: { mode: "view" } as never,
        })
      })
      .catch(() => {
        // The share may not have landed yet, or was withdrawn. Leaving them
        // where they are beats throwing an error at somebody who just signed up.
      })
    return () => {
      cancelled = true
    }
  }, [navigate, queryClient])
}
