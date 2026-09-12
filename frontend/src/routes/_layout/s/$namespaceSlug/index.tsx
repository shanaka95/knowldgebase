import { useQuery, useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Suspense } from "react"
import { PageContainer } from "@/components/Layout/PageContainer"
import { FolderContents } from "@/components/Namespaces/FolderContents"
import { NamespaceHeader } from "@/components/Namespaces/NamespaceHeader"
import { PendingHeader, PendingList } from "@/components/Pending/PendingList"
import { canEditNamespace } from "@/hooks/useNamespaces"
import { namespaceBySlugQuery, treeQuery } from "@/queries/namespaces"

export const Route = createFileRoute("/_layout/s/$namespaceSlug/")({
  component: SpaceHome,
})

function SpaceHomeContent() {
  const { namespaceSlug } = Route.useParams()
  const { data: namespace } = useSuspenseQuery(
    namespaceBySlugQuery(namespaceSlug),
  )
  const { data: index, isPending } = useQuery(treeQuery(namespace.id))

  return (
    <>
      <NamespaceHeader namespace={namespace} />
      {isPending || !index ? (
        <PendingList />
      ) : (
        <FolderContents
          namespaceId={namespace.id}
          namespaceSlug={namespace.slug}
          folderId={null}
          folders={index.childrenOf(null)}
          documents={index.docsOf(null)}
          canEdit={canEditNamespace(namespace)}
        />
      )}
    </>
  )
}

function SpaceHome() {
  return (
    <PageContainer className="flex flex-col gap-8">
      <Suspense
        fallback={
          <>
            <PendingHeader />
            <PendingList />
          </>
        }
      >
        <SpaceHomeContent />
      </Suspense>
    </PageContainer>
  )
}
