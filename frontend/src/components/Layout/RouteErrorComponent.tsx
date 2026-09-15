import { useRouter, useRouterState } from "@tanstack/react-router"
import { AxiosError } from "axios"
import { AlertTriangle, Check, Copy, RefreshCw } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import {
  isStaleChunkError,
  recoverFromStaleBuild,
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
  const path = useRouterState({ select: (s) => s.location.href })
  const status = getErrorStatus(error)
  const [updating, setUpdating] = useState(false)

  // Nothing is assumed about whether recovery will happen: it is asked, and
  // "Updating" is shown only once something has actually started. Deciding from
  // the error alone parked the page on that message for ever whenever recovery
  // declined - which is most of the time, since it declines precisely when it
  // has already been tried.
  //
  // A failed import says so plainly. Everything else gets asked rather than
  // guessed: a replaced chunk can also surface as a router holding a match whose
  // route is undefined, and matching on the wording of *that* would mean chasing
  // every future phrasing of the same thing.
  useEffect(() => {
    let cancelled = false
    const started = isStaleChunkError(error)
      ? recoverFromStaleBuild(error)
      : status === undefined
        ? reloadIfStale()
        : Promise.resolve(false)

    void started.then((recovering) => {
      if (recovering && !cancelled) setUpdating(true)
    })
    return () => {
      cancelled = true
    }
  }, [error, status])

  // A reload can be refused, blocked or simply slow, and a message that outlives
  // the thing it is waiting for is worse than an error: it says the problem is
  // being handled when nobody is handling it. So the claim expires.
  useEffect(() => {
    if (!updating) return
    const timer = setTimeout(() => setUpdating(false), 15_000)
    return () => clearTimeout(timer)
  }, [updating])

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
          <span className="flex flex-wrap items-center justify-center gap-2">
            <Button
              variant="outline"
              onClick={() => {
                reset?.()
                router.invalidate()
              }}
            >
              Try again
            </Button>
            {/*
              A second, blunter option. "Try again" re-runs the route, which
              cannot help when the problem is the code the page is running -
              and that is the case this error most often turns out to be.
            */}
            <Button
              variant="ghost"
              onClick={() => window.location.reload()}
              data-testid="route-error-reload"
            >
              <RefreshCw />
              Reload the app
            </Button>
          </span>
        }
      />
      <ErrorDetail error={error} href={path} />
    </div>
  )
}

/**
 * What actually happened, for somebody who has to report it.
 *
 * Folded away, because a stack trace is not what a reader needs first. But it
 * is there, and it copies in one press: "Something went wrong" with no detail
 * costs a round of guessing every time, and this error class in particular has
 * cost several.
 */
function ErrorDetail({ error, href }: { error: unknown; href: string }) {
  const [copied, setCopied] = useState(false)
  if (!(error instanceof Error)) return null

  const report = [
    `Page: ${href}`,
    `Error: ${error.name}: ${error.message}`,
    `When: ${new Date().toISOString()}`,
    // The entry chunk names the build, which is the first thing to check when
    // a report says "it works for me". Empty string, not just null: a module
    // script without a src is a dev server, not a missing answer.
    `Build: ${
      document.querySelector<HTMLScriptElement>('script[type="module"]')?.src ||
      "unknown (development)"
    }`,
    "",
    error.stack ?? "(no stack)",
  ].join("\n")

  return (
    <details className="mx-auto mt-6 max-w-2xl rounded-lg border bg-muted/20 text-sm">
      <summary className="cursor-pointer px-4 py-2.5 text-muted-foreground select-none">
        Technical details
      </summary>
      <div className="flex flex-col gap-2 border-t px-4 py-3">
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all font-mono text-muted-foreground text-xs">
          {report}
        </pre>
        <Button
          variant="outline"
          size="sm"
          className="self-start"
          data-testid="route-error-copy"
          onClick={() => {
            void navigator.clipboard?.writeText(report).then(() => {
              setCopied(true)
              setTimeout(() => setCopied(false), 2000)
            })
          }}
        >
          {copied ? <Check /> : <Copy />}
          {copied ? "Copied" : "Copy details"}
        </Button>
      </div>
    </details>
  )
}
