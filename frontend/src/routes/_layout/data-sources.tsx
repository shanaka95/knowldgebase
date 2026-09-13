import { createFileRoute } from "@tanstack/react-router"
import { Database } from "lucide-react"

import { PageContainer, PageHeader } from "@/components/Layout/PageContainer"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"

export const Route = createFileRoute("/_layout/data-sources")({
  component: DataSourcesPage,
  staticData: { crumb: "Data sources" },
  head: () => ({ meta: [{ title: "Data sources - PlusGPT" }] }),
})

function DataSourcesPage() {
  return (
    <PageContainer className="flex flex-col gap-6">
      <PageHeader
        title="Data sources"
        description="Places your documents arrive from on their own, so you do not have to upload them."
      />
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <Database />
          </EmptyMedia>
          <EmptyTitle>Nothing to connect yet</EmptyTitle>
          <EmptyDescription>
            Connecting a mailbox or a drive will let documents flow into your
            knowledge base automatically — invoices, statements and letters
            filed as they arrive. Until then, use Imports to add files yourself,
            or send them to an agent.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    </PageContainer>
  )
}
