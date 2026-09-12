import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link as RouterLink } from "@tanstack/react-router"
import { CircleCheck, FileText } from "lucide-react"
import { z } from "zod"

import { AuthAlert } from "@/components/Common/AuthAlert"
import { AuthLayout } from "@/components/Common/AuthLayout"
import { APP_NAME } from "@/components/Common/Logo"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { rememberInvitedDocument } from "@/hooks/usePendingInvite"
import { shortDate } from "@/lib/format"
import { invitationPreviewQuery } from "@/queries/sharing"
import { extractErrorMessage } from "@/utils"

export const Route = createFileRoute("/invite")({
  component: Invite,
  validateSearch: z.object({
    token: z.string().optional().catch(undefined),
  }),
  head: () => ({
    meta: [{ title: `You've been invited - ${APP_NAME}` }],
  }),
})

function Invite() {
  const { token } = Route.useSearch()

  // Deliberately outside every authenticated layout: whoever follows this link
  // has no account yet, which is the entire point of sending it.
  const preview = useQuery({
    ...invitationPreviewQuery(token ?? ""),
    enabled: Boolean(token),
  })

  if (!token || preview.isError) {
    return (
      <AuthLayout>
        <div className="flex flex-col gap-6" data-testid="invite-failed">
          <div className="flex flex-col items-center gap-2 text-center">
            <h1 className="text-2xl font-bold">
              That invitation link did not work
            </h1>
          </div>

          <AuthAlert>
            {preview.error
              ? extractErrorMessage(preview.error)
              : "This invitation link is missing its token. Ask for a new one."}
          </AuthAlert>

          <p className="text-center text-sm text-muted-foreground">
            Ask whoever shared the page to send it again.
          </p>

          <div className="text-center text-sm">
            <RouterLink to="/login" className="underline underline-offset-4">
              Back to login
            </RouterLink>
          </div>
        </div>
      </AuthLayout>
    )
  }

  const invitation = preview.data
  if (!invitation) {
    return (
      <AuthLayout>
        <div
          className="flex flex-col items-center gap-3 text-center"
          data-testid="invite-pending"
        >
          <Spinner className="size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Checking this invitation…
          </p>
        </div>
      </AuthLayout>
    )
  }

  if (invitation.already_accepted) {
    return (
      <AuthLayout>
        <div className="flex flex-col gap-6" data-testid="invite-accepted">
          <div className="flex flex-col items-center gap-2 text-center">
            <CircleCheck className="size-8 text-muted-foreground" />
            <h1 className="text-2xl font-bold">You already have this page</h1>
            <p className="text-sm text-muted-foreground">
              “{invitation.document_title}” is waiting in {APP_NAME}. Log in as{" "}
              {invitation.email} to read it.
            </p>
          </div>
          <Button asChild className="w-full">
            <RouterLink
              to="/login"
              onClick={() => rememberInvitedDocument(invitation.document_id)}
            >
              Log in
            </RouterLink>
          </Button>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout>
      <div className="flex flex-col gap-6" data-testid="invite-landing">
        <div className="flex flex-col items-center gap-2 text-center">
          <FileText className="size-8 text-muted-foreground" />
          <h1 className="text-2xl font-bold">
            {invitation.shared_by} shared “{invitation.document_title}” with you
          </h1>
          <p className="text-sm text-muted-foreground">
            Create a {APP_NAME} account on {invitation.email} and the page opens
            as soon as you confirm that address. You'll be able to{" "}
            {invitation.role === "editor" ? "read and edit it" : "read it"}.
          </p>
        </div>

        <div className="grid gap-3">
          <Button
            asChild
            className="w-full"
            data-testid="invite-create-account"
          >
            <RouterLink
              to="/signup"
              search={{ email: invitation.email }}
              onClick={() => rememberInvitedDocument(invitation.document_id)}
            >
              Create an account
            </RouterLink>
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            This invitation expires {shortDate(invitation.expires_at)}.
          </p>
        </div>

        <div className="text-center text-sm">
          Already have an account on that address?{" "}
          <RouterLink
            to="/login"
            className="underline underline-offset-4"
            onClick={() => rememberInvitedDocument(invitation.document_id)}
          >
            Log in
          </RouterLink>
        </div>
      </div>
    </AuthLayout>
  )
}
