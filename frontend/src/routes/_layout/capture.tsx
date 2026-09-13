import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { FileUp } from "lucide-react"
import {
  ImportsList,
  ImportsListSkeleton,
} from "@/components/Imports/ImportsList"
import { PageContainer, PageHeader } from "@/components/Layout/PageContainer"
import { Button } from "@/components/ui/button"
import { importsQuery } from "@/queries/imports"
import { openDialog } from "@/stores/dialogs"

export const Route = createFileRoute("/_layout/capture")({
  component: CapturePage,
  staticData: { crumb: "Capture" },
  loader: ({ context: { queryClient } }) => {
    void queryClient.prefetchQuery(importsQuery())
  },
  head: () => ({ meta: [{ title: "Capture - PlusGPT" }] }),
})

function CapturePage() {
  const { data, isPending } = useQuery(importsQuery())

  return (
    <PageContainer className="flex flex-col gap-6">
      <PageHeader
        title="Capture"
        description="Photograph a document or choose a file, and it becomes a page you can search. The original stays attached to it."
        actions={
          <Button
            onClick={() => openDialog({ kind: "import" })}
            data-testid="import-new"
          >
            <FileUp />
            Add a document
          </Button>
        }
      />
      {isPending || !data ? (
        <ImportsListSkeleton />
      ) : (
        <ImportsList jobs={data.data} />
      )}
    </PageContainer>
  )
}
