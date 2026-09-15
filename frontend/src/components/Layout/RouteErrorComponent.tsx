import { useRouter } from "@tanstack/react-router"
import { AxiosError } from "axios"
import { AlertTriangle, RefreshCw } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import {
  isStaleChunkError,
  reloadForNewBuild,
  reloadIfStale,
} from "@/lib/staleBuild"
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
  const [updating, setUpdating] = useState(() => isStaleChunkError(error))

  // A failed import says so plainly and is handled above. Everything else gets
  // asked rather than guessed: a replaced chunk can also surface as a router
  // holding a match whose route is undefined, and matching on the wording of
  // *that* would mean chasing every future phrasing of the same thing.
  useEffect(() => {
    let cancelled = false
    if (isStaleChunkError(error)) {
      reloadForNewBuild()
      return
    }
    // Only for genuine failures, and only once: an error that is not a stale
    // build must keep showing, because reloading past a real bug hides it.
    if (status === undefined) {
      void reloadIfStale().then((reloading) => {
        if (reloading && !cancelled) setUpdating(true)
      })
    }
    return () => {
      cancelled = true
    }
  }, [error, status])

  if (updating) {
    return (
      <div className="p-6 md:p-10" data-testid="route-updating">
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
