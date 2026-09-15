import { useRouter } from "@tanstack/react-router"
import { AxiosError } from "axios"
import { AlertTriangle, RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { isStaleChunkError, reloadForNewBuild } from "@/lib/staleBuild"
import { EmptyState } from "./EmptyState"
import { NoAccess } from "./NoAccess"
import { NotFoundState } from "./NotFoundState"

export function getErrorStatus(error: unknown): number | undefined {
  if (error instanceof AxiosError) return error.response?.status
  return undefined
}

export function RouteErrorComponent({
  error,
  reset,
}: {
  error: unknown
  reset?: () => void
}) {
  const router = useRouter()
  const status = getErrorStatus(error)

  // A deploy replaced the chunk this route lives in. Reloading picks up the
  // new one; `reloadForNewBuild` does it at most once, so a genuine failure
  // still surfaces instead of looping.
  if (isStaleChunkError(error) && reloadForNewBuild()) {
    return (
      <div className="p-6 md:p-10" data-testid="route-error">
        <EmptyState
          icon={RefreshCw}
          title="Updating"
          description="A new version was released. Loading it now…"
        />
      </div>
    )
  }

  if (status === 403) return <NoAccess />
  if (status === 404) return <NotFoundState />

  const message =
    error instanceof Error ? error.message : "Something went wrong."

  return (
    <div className="p-6 md:p-10" data-testid="route-error">
      <EmptyState
        icon={AlertTriangle}
        title="Something went wrong"
        description={message}
        action={
          <Button
            variant="outline"
            onClick={() => {
              reset?.()
              router.invalidate()
            }}
          >
            Try again
          </Button>
        }
      />
    </div>
  )
}
