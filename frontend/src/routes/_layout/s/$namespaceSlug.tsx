import { createFileRoute, Outlet } from "@tanstack/react-router"

import { NotFoundState } from "@/components/Layout/NotFoundState"
import { RouteErrorComponent } from "@/components/Layout/RouteErrorComponent"
import { rememberNamespaceSlug } from "@/hooks/useNamespaces"
import type { Crumb } from "@/lib/breadcrumbs"
import { namespaceBySlugQuery, treeQuery } from "@/queries/namespaces"

/**
 * Space layout route: resolves the slug to a namespace, warms the tree and
 * exposes the space crumb for the header.
 */
export const Route = createFileRoute("/_layout/s/$namespaceSlug")({
  component: () => <Outlet />,
  errorComponent: RouteErrorComponent,
  notFoundComponent: () => <NotFoundState />,
  loader: async ({ context: { queryClient }, params }) => {
    const namespace = await queryClient.ensureQueryData(
      namespaceBySlugQuery(params.namespaceSlug),
    )
    rememberNamespaceSlug(namespace.slug)
    // warm the sidebar tree; don't block navigation on it
    void queryClient.prefetchQuery(treeQuery(namespace.id))
    const crumbs: Crumb[] = [
      { label: namespace.name, to: `/s/${namespace.slug}` },
    ]
    return { namespace, crumbs }
  },
  head: ({ loaderData }) => ({
    meta: [
      {
        title: `${loaderData?.namespace.name ?? "Space"} - Knowledge Base`,
      },
    ],
  }),
})
