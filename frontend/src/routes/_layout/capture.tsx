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
  staticData: { crumb: "Upload documents" },
  loader: ({ context: { queryClient } }) => {
    void queryClient.prefetchQuery(importsQuery())
  },
  head: () => ({ meta: [{ title: "Upload documents - PlusGPT" }] }),
})

function CapturePage() {
  const { data, isPending } = useQuery(importsQuery())

  return (
    <PageContainer className="flex flex-col gap-6">
      <PageHeader
        title="Upload documents"
        description="Choose a file or photograph a document, and it becomes a page you can search. The original stays attached to it."
        actions={
          <Button
            onClick={() => openDialog({ kind: "import" })}
            data-testid="import-new"
          >
            <FileUp />
            Upload a document
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
