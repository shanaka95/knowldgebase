import { useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useEffect } from "react"

import { documentQuery } from "@/queries/documents"
import { namespaceQuery } from "@/queries/namespaces"

const KEY = "kb:pendingInvite"

/** An invitation is for one page, or for a whole space. Both end somewhere. */
export type PendingInvite =
  | { type: "document"; id: string }
  | { type: "namespace"; id: string }

/**
 * Remember what an invitation was for, so the sign-up → confirm → sign-in
 * detour can end where it started. Session storage because it is one journey in
 * one tab, and because a stale id left behind for weeks would be worse than
 * losing it when the tab closes.
 */
export function rememberInvitedTarget(target: PendingInvite) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(target))
  } catch {
    /* private browsing, or storage disabled — the landing page still works */
  }
}

function takeInvitedTarget(): PendingInvite | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    sessionStorage.removeItem(KEY)
    const parsed = JSON.parse(raw) as PendingInvite
    if (
      (parsed?.type === "document" || parsed?.type === "namespace") &&
      typeof parsed.id === "string"
    ) {
      return parsed
    }
    return null
  } catch {
    // Unreadable storage, or a value written by an older build.
    return null
  }
}

/**
 * Once the invited person is signed in, take them to what they were sent.
 * Mounted in the authenticated layout, so it fires wherever they land.
 */
export function usePendingInviteRedirect() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  useEffect(() => {
    // Reading the target also clears it, so the effect running twice (as it
    // does under StrictMode) is harmless — and there is deliberately no cleanup
    // flag, because cancelling the first run would cancel the only run.
    const target = takeInvitedTarget()
    if (!target) return
    const journey =
      target.type === "document"
        ? queryClient.fetchQuery(documentQuery(target.id)).then((document) => {
            if (!document.namespace_slug) return
            navigate({
              to: "/s/$namespaceSlug/d/$documentId",
              params: {
                namespaceSlug: document.namespace_slug,
                documentId: document.id,
              },
              search: { mode: "view" } as never,
            })
          })
        : queryClient
            .fetchQuery(namespaceQuery(target.id))
            .then((namespace) => {
              navigate({
                to: "/s/$namespaceSlug",
                params: { namespaceSlug: namespace.slug },
              })
            })
    journey.catch(() => {
      // The share may not have landed yet, or was withdrawn. Leaving them
      // where they are beats throwing an error at somebody who just signed up.
    })
  }, [navigate, queryClient])
}
