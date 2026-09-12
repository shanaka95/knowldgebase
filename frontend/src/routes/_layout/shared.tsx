import { createFileRoute } from "@tanstack/react-router"

import { PageContainer, PageHeader } from "@/components/Layout/PageContainer"
import { SharedList } from "@/components/Shared/SharedList"
import { sharedWithMeQuery } from "@/queries/shared"

export const Route = createFileRoute("/_layout/shared")({
  component: SharedPage,
  staticData: { crumb: "Shared with me" },
  loader: ({ context: { queryClient } }) => {
    void queryClient.prefetchQuery(sharedWithMeQuery())
  },
  head: () => ({ meta: [{ title: "Shared with me - PlusGPT" }] }),
})

function SharedPage() {
  return (
    <PageContainer className="flex flex-col gap-6">
      <PageHeader
        title="Shared with me"
        description="Spaces and pages other people have shared with you."
      />
      <SharedList />
    </PageContainer>
  )
}
