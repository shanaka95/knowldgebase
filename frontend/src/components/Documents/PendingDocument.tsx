import { Skeleton } from "@/components/ui/skeleton"

export function PendingDocument() {
  return (
    <div
      className="flex w-full gap-8 px-4 py-6 md:px-8 md:py-8"
      data-testid="pending-document"
    >
      <div className="kb-editor-column mx-auto flex w-full flex-col gap-6">
        <div className="flex items-center justify-between">
          <Skeleton className="h-6 w-28 rounded-full" />
          <div className="flex gap-2">
            <Skeleton className="h-8 w-16" />
            <Skeleton className="size-8" />
          </div>
        </div>
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-4 w-48" />
        <div className="flex flex-col gap-3 pt-4">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="mt-4 h-32 w-full" />
        </div>
      </div>
      <aside className="hidden w-[320px] shrink-0 lg:block">
        <div className="flex flex-col gap-2 pt-16">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-3 w-32" />
          <Skeleton className="h-3 w-36" />
        </div>
      </aside>
    </div>
  )
}

export default PendingDocument
