import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { Suspense } from "react"
import { z } from "zod"

import { NoAccess } from "@/components/Layout/NoAccess"
import { PageContainer, PageHeader } from "@/components/Layout/PageContainer"
import { RouteErrorComponent } from "@/components/Layout/RouteErrorComponent"
import { NamespaceDangerZone } from "@/components/Namespaces/NamespaceDangerZone"
import { NamespaceGeneralSettings } from "@/components/Namespaces/NamespaceGeneralSettings"
import { NamespaceMembers } from "@/components/Namespaces/NamespaceMembers"
import { PendingHeader, PendingList } from "@/components/Pending/PendingList"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { canAdminNamespace } from "@/hooks/useNamespaces"
import type { Crumb } from "@/lib/breadcrumbs"
import { namespaceBySlugQuery } from "@/queries/namespaces"

const TABS = ["general", "members", "danger"] as const
type Tab = (typeof TABS)[number]

export const Route = createFileRoute("/_layout/s/$namespaceSlug/settings")({
  component: SpaceSettings,
  errorComponent: RouteErrorComponent,
  validateSearch: z.object({ tab: z.enum(TABS).catch("general") }),
  loader: async ({ context: { queryClient }, params }) => {
    const namespace = await queryClient.ensureQueryData(
      namespaceBySlugQuery(params.namespaceSlug),
    )
    const crumbs: Crumb[] = [
      { label: namespace.name, to: `/s/${namespace.slug}` },
      { label: "Settings", to: `/s/${namespace.slug}/settings` },
    ]
    return { crumbs }
  },
  head: () => ({ meta: [{ title: "Space settings - PlusGPT" }] }),
})

function SpaceSettingsContent() {
  const { namespaceSlug } = Route.useParams()
  const { tab } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const { data: namespace } = useSuspenseQuery(
    namespaceBySlugQuery(namespaceSlug),
  )

  if (!canAdminNamespace(namespace)) return <NoAccess />

  return (
    <>
      <PageHeader
        title={`${namespace.name} settings`}
        description="Manage how this space looks, who can access it, and its lifecycle."
      />
      <Tabs
        value={tab}
        onValueChange={(v) =>
          navigate({ search: { tab: v as Tab }, replace: true })
        }
      >
        <TabsList>
          <TabsTrigger value="general">General</TabsTrigger>
          <TabsTrigger value="members" data-testid="space-members-tab">
            Members
          </TabsTrigger>
          <TabsTrigger value="danger">Danger zone</TabsTrigger>
        </TabsList>
        <TabsContent value="general" className="pt-4">
          <NamespaceGeneralSettings namespace={namespace} />
        </TabsContent>
        <TabsContent value="members" className="pt-4">
          <NamespaceMembers namespace={namespace} />
        </TabsContent>
        <TabsContent value="danger" className="pt-4">
          <NamespaceDangerZone namespace={namespace} />
        </TabsContent>
      </Tabs>
    </>
  )
}

function SpaceSettings() {
  return (
    <PageContainer className="flex flex-col gap-6" size="narrow">
      <Suspense
        fallback={
          <>
            <PendingHeader />
            <PendingList rows={4} />
          </>
        }
      >
        <SpaceSettingsContent />
      </Suspense>
    </PageContainer>
  )
}
