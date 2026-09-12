import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link as RouterLink } from "@tanstack/react-router"
import { CircleCheck, FileText, FolderKanban } from "lucide-react"
import { z } from "zod"

import { AuthAlert } from "@/components/Common/AuthAlert"
import { AuthLayout } from "@/components/Common/AuthLayout"
import { APP_NAME } from "@/components/Common/Logo"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import {
  type PendingInvite,
  rememberInvitedTarget,
} from "@/hooks/usePendingInvite"
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

  // An invitation is for one page or for a whole space, and the two grants are
  // not the same thing; every sentence below names which one this is.
  const isSpace = invitation.target === "space"
  const noun = isSpace ? "space" : "page"
  const pending: PendingInvite | null = invitation.namespace_id
    ? { type: "namespace", id: invitation.namespace_id }
    : invitation.document_id
      ? { type: "document", id: invitation.document_id }
      : null
  const remember = () => {
    if (pending) rememberInvitedTarget(pending)
  }
  const ability = isSpace
    ? ({
        admin: "read, edit and manage everything in it",
        editor: "create and edit pages anywhere in it",
      }[invitation.role] ?? "read every page in it")
    : invitation.role === "editor"
      ? "read and edit it"
      : "read it"

  if (invitation.already_accepted) {
    return (
      <AuthLayout>
        <div className="flex flex-col gap-6" data-testid="invite-accepted">
          <div className="flex flex-col items-center gap-2 text-center">
            <CircleCheck className="size-8 text-muted-foreground" />
            <h1 className="text-2xl font-bold">You already have this {noun}</h1>
            <p className="text-sm text-muted-foreground">
              “{invitation.document_title}” is waiting in {APP_NAME}. Log in as{" "}
              {invitation.email} to read it.
            </p>
          </div>
          <Button asChild className="w-full">
            <RouterLink to="/login" onClick={remember}>
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
          {isSpace ? (
            <FolderKanban className="size-8 text-muted-foreground" />
          ) : (
            <FileText className="size-8 text-muted-foreground" />
          )}
          <h1 className="text-2xl font-bold">
            {invitation.shared_by} shared {isSpace ? "the space " : ""}“
            {invitation.document_title}” with you
          </h1>
          <p className="text-sm text-muted-foreground">
            Create a {APP_NAME} account on {invitation.email} and the {noun}{" "}
            opens as soon as you confirm that address. You'll be able to{" "}
            {ability}.
            {isSpace
              ? " That covers every page in the space, including ones added later."
              : ""}
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
              onClick={remember}
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
            onClick={remember}
          >
            Log in
          </RouterLink>
        </div>
      </div>
    </AuthLayout>
  )
}
