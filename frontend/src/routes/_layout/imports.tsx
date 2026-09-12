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

export const Route = createFileRoute("/_layout/imports")({
  component: ImportsPage,
  staticData: { crumb: "Imports" },
  loader: ({ context: { queryClient } }) => {
    void queryClient.prefetchQuery(importsQuery())
  },
  head: () => ({ meta: [{ title: "Imports - PlusGPT" }] }),
})

function ImportsPage() {
  const { data, isPending } = useQuery(importsQuery())

  return (
    <PageContainer className="flex flex-col gap-6">
      <PageHeader
        title="Imports"
        description="PDFs and images you turned into pages. The original file stays attached to the page it created."
        actions={
          <Button
            onClick={() => openDialog({ kind: "import" })}
            data-testid="import-new"
          >
            <FileUp />
            Import a file
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
