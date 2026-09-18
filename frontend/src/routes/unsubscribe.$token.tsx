import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link as RouterLink } from "@tanstack/react-router"
import { CircleCheck } from "lucide-react"

import { PublicService } from "@/client"
import { AuthAlert } from "@/components/Common/AuthAlert"
import { AuthLayout } from "@/components/Common/AuthLayout"
import { Spinner } from "@/components/ui/spinner"
import { extractErrorMessage } from "@/utils"

export const Route = createFileRoute("/unsubscribe/$token")({
  component: Unsubscribe,
  head: () => ({
    meta: [
      { title: "Unsubscribe - PlusGPT" },
      { name: "robots", content: "noindex" },
    ],
  }),
})

/**
 * One click, and the click is the point.
 *
 * The request is a POST, fired from here on mount rather than by following the
 * link itself. Outlook Safe Links, Gmail's proxy and most corporate scanners
 * fetch every URL in a message before a human sees it, so a link that acted on
 * GET would unsubscribe a large part of any list within minutes of sending to
 * it, and nobody would find out until the next campaign reached nobody. A
 * scanner reads this page and runs no JavaScript, so nothing happens; a person
 * opens it and it is already done.
 */
function Unsubscribe() {
  const { token } = Route.useParams()

  // A query that happens to POST, which is what `verify-email` does with the
  // confirmation link and for the same reasons: it fires once on mount with no
  // effect to write, it must not be retried, and it must never be refetched
  // behind the reader's back - a second attempt would report a link that
  // worked as one that did not.
  const leave = useQuery({
    queryKey: ["unsubscribe", token],
    queryFn: async () =>
      (await PublicService.unsubscribe({ path: { token } })).data,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
    refetchOnMount: false,
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
  })

  if (leave.isPending) {
    return (
      <AuthLayout>
        <div
          className="flex flex-col items-center gap-3 text-center"
          data-testid="unsubscribe-pending"
        >
          <Spinner className="size-6 text-muted-foreground" />
          <p className="text-muted-foreground text-sm">One moment…</p>
        </div>
      </AuthLayout>
    )
  }

  if (leave.isSuccess) {
    return (
      <AuthLayout>
        <div className="flex flex-col gap-6" data-testid="unsubscribe-success">
          <div className="flex flex-col items-center gap-2 text-center">
            <CircleCheck className="size-8 text-muted-foreground" />
            <h1 className="font-bold text-2xl">Unsubscribed</h1>
            <p className="text-muted-foreground text-sm">
              You will not get any more email from us. Sorry for the
              interruption.
            </p>
          </div>
          <div className="text-center text-sm">
            <RouterLink to="/" className="underline underline-offset-4">
              Go to PlusGPT
            </RouterLink>
          </div>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout>
      <div className="flex flex-col gap-6" data-testid="unsubscribe-failed">
        <div className="flex flex-col items-center gap-2 text-center">
          <h1 className="font-bold text-2xl">That link did not work</h1>
        </div>
        <AuthAlert>
          {leave.error
            ? extractErrorMessage(leave.error)
            : "This link is not one of ours."}
        </AuthAlert>
        <p className="text-center text-muted-foreground text-sm">
          Reply to the message you received and I will take you off the list by
          hand.
        </p>
      </div>
    </AuthLayout>
  )
}
