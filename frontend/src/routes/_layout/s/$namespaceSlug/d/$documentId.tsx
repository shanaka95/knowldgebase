import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router"
import { z } from "zod"

import { DocumentNotFound } from "@/components/Documents/DocumentNotFound"
import { DocumentPage } from "@/components/Documents/DocumentPage"
import { PendingDocument } from "@/components/Documents/PendingDocument"
import { NoAccess } from "@/components/Layout/NoAccess"
import {
  getErrorStatus,
  RouteErrorComponent,
} from "@/components/Layout/RouteErrorComponent"
import { documentQuery } from "@/queries/documents"

export const documentSearchSchema = z.object({
  mode: z.enum(["view", "edit"]).catch("view"),
  panel: z.enum(["ai", "toc"]).optional().catch(undefined),
})

export const Route = createFileRoute("/_layout/s/$namespaceSlug/d/$documentId")(
  {
    component: DocumentRoute,
    validateSearch: documentSearchSchema,
    loaderDeps: ({ search }) => ({ mode: search.mode, panel: search.panel }),
    loader: async ({ context: { queryClient }, params, deps }) => {
      const document = await queryClient.ensureQueryData(
        documentQuery(params.documentId),
      )
      if (
        document.namespace_slug &&
        document.namespace_slug !== params.namespaceSlug
      ) {
        throw redirect({
          to: "/s/$namespaceSlug/d/$documentId",
          params: {
            namespaceSlug: document.namespace_slug,
            documentId: params.documentId,
          },
          search: { mode: deps.mode, panel: deps.panel },
          replace: true,
        })
      }
      return { title: document.title }
    },
    head: ({ loaderData }) => ({
      meta: [{ title: `${loaderData?.title ?? "Page"} - Knowledge Base` }],
    }),
    pendingComponent: PendingDocument,
    errorComponent: DocumentRouteError,
  },
)

function DocumentRouteError({
  error,
  reset,
}: {
  error: unknown
  reset?: () => void
}) {
  const status = getErrorStatus(error)
  if (status === 403) return <NoAccess />
  if (status === 404) return <DocumentNotFound />
  return <RouteErrorComponent error={error} reset={reset} />
}

function DocumentRoute() {
  const { documentId, namespaceSlug } = Route.useParams()
  const { mode, panel } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })

  return (
    <DocumentPage
      key={documentId}
      documentId={documentId}
      namespaceSlug={namespaceSlug}
      mode={mode}
      panel={panel}
      onChangeSearch={(patch) =>
        void navigate({
          search: (prev) => ({ ...prev, ...patch }),
          replace: true,
        })
      }
    />
  )
}
