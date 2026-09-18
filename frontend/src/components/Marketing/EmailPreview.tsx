import { Skeleton } from "@/components/ui/skeleton"

/**
 * The message, as the person receiving it sees it.
 *
 * Rendered by the server, through the same function that sends it, so this is
 * the message rather than a second implementation that will drift from it.
 *
 * The iframe is sandboxed with no permissions at all. What is being rendered is
 * HTML somebody pasted into a textarea, inside a superuser's own session: it
 * has no business running scripts, reaching storage, or navigating anything.
 * `srcDoc` rather than a blob URL, so it inherits no origin either.
 */
export function EmailPreview({
  html,
  subject,
  to,
  loading,
}: {
  html?: string
  subject?: string
  to?: string
  loading?: boolean
}) {
  if (loading) {
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-80 w-full" />
      </div>
    )
  }
  if (!html) {
    return (
      <p className="text-muted-foreground text-sm">
        Write a message, then preview it to see what lands in the inbox.
      </p>
    )
  }
  return (
    <div
      className="flex min-w-0 flex-col gap-2"
      data-testid="marketing-preview"
    >
      <div className="min-w-0 rounded-md border bg-muted/30 px-3 py-2 text-sm">
        <p className="wrap-anywhere">
          <span className="text-muted-foreground">To </span>
          {to}
        </p>
        <p className="wrap-anywhere font-medium">{subject}</p>
      </div>
      <iframe
        title="Message preview"
        srcDoc={html}
        sandbox=""
        className="h-[460px] w-full rounded-md border bg-white"
        data-testid="marketing-preview-frame"
      />
    </div>
  )
}
