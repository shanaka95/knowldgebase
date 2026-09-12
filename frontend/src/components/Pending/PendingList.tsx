import { Skeleton } from "@/components/ui/skeleton"

export function PendingList({ rows = 6 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2" aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  )
}

export function PendingHeader() {
  return (
    <div className="flex items-start gap-4" aria-busy="true">
      <Skeleton className="size-12 rounded-lg" />
      <div className="flex flex-col gap-2">
        <Skeleton className="h-7 w-48" />
        <Skeleton className="h-4 w-72" />
      </div>
    </div>
  )
}
