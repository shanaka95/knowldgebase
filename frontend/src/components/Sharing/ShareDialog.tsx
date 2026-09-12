import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import {
  DocumentsService,
  type NamespaceRole,
  NamespacesService,
  type ShareResult,
  type ShareRole,
  type SpaceShareResult,
} from "@/client"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { canAdminNamespace, canEditNamespace } from "@/hooks/useNamespaces"
import { queryKeys } from "@/lib/queryKeys"
import {
  namespaceInvitationsQuery,
  namespaceMembersQuery,
  namespaceQuery,
} from "@/queries/namespaces"
import {
  documentInvitationsQuery,
  documentSharesQuery,
} from "@/queries/sharing"
import type { DialogTarget } from "@/stores/dialogs"
import { handleError } from "@/utils"
import { AccessList, type RoleOption } from "./AccessList"
import { PublicLinkSection } from "./PublicLinkSection"
import {
  plural,
  ShareComposer,
  ShareCounter,
  ShareOutcome,
  useRecipients,
} from "./ShareComposer"

const DOC_ROLES: RoleOption[] = [
  { value: "viewer", label: "Can view", hint: "Read the page" },
  { value: "editor", label: "Can edit", hint: "Read and edit the page" },
]
const NS_ROLES: RoleOption[] = [
  { value: "viewer", label: "Viewer", hint: "Read every page in the space" },
  {
    value: "editor",
    label: "Editor",
    hint: "Create and edit pages and folders",
  },
  { value: "admin", label: "Admin", hint: "Manage members and settings" },
]

// --- spaces -------------------------------------------------------------------

function NamespaceShare({
  target,
}: {
  target: Extract<DialogTarget, { type: "namespace" }>
}) {
  const queryClient = useQueryClient()
  const { user: me } = useAuth()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const namespace = useQuery(namespaceQuery(target.id))
  const ns = namespace.data
  // Sharing a space hands over everything in it, now and later — the backend
  // allows that to space admins only and answers anyone else with a 403.
  const canShare = canAdminNamespace(ns)

  const members = useQuery(namespaceMembersQuery(target.id))
  // Everyone in the space may read the pending invitations, so the count below
  // is the same number an admin sees — and matches what the backend counts.
  const invitations = useQuery(namespaceInvitationsQuery(target.id))

  const [role, setRole] = useState<NamespaceRole>("viewer")
  const [message, setMessage] = useState("")
  const [result, setResult] = useState<SpaceShareResult | null>(null)
  const recipients = useRecipients(() => setResult(null))

  const used =
    (members.data?.data.length ?? 0) + (invitations.data?.length ?? 0)
  // The ceiling belongs to the space owner; the reply to a share is the only
  // place it is stated, so fall back to our own until one comes back.
  const limit = result?.max_members ?? me?.max_members_per_space ?? null
  const atLimit = limit !== null && used >= limit

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.namespaces.members(target.id),
    })
    queryClient.invalidateQueries({
      queryKey: queryKeys.namespaces.invitations(target.id),
    })
    queryClient.invalidateQueries({ queryKey: queryKeys.namespaces.all })
    queryClient.invalidateQueries({ queryKey: queryKeys.shared })
  }

  const share = useMutation({
    mutationFn: async () =>
      (
        await NamespacesService.addNamespaceMembers({
          path: { namespace_id: target.id },
          body: {
            emails: recipients.valid,
            role,
            message: message.trim() || null,
          },
        })
      ).data,
    onSuccess: (data) => {
      setResult(data)
      recipients.clear()
      setMessage("")
      invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })

  const update = useMutation({
    mutationFn: (v: { userId: string; role: string }) =>
      NamespacesService.updateNamespaceMember({
        path: { namespace_id: target.id, user_id: v.userId },
        body: { role: v.role as NamespaceRole },
      }),
    onSuccess: invalidate,
    onError: (e) => {
      handleError.call(showErrorToast, e)
      invalidate()
    },
  })
  const remove = useMutation({
    mutationFn: (userId: string) =>
      NamespacesService.removeNamespaceMember({
        path: { namespace_id: target.id, user_id: userId },
      }),
    onSuccess: () => {
      showSuccessToast("Access removed")
      invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const withdraw = useMutation({
    mutationFn: (invitationId: string) =>
      NamespacesService.cancelNamespaceInvitation({
        path: { namespace_id: target.id, invitation_id: invitationId },
      }),
    onSuccess: () => {
      showSuccessToast("Invitation withdrawn")
      invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <>
      <DialogHeader>
        <DialogTitle>Share space “{target.name}”</DialogTitle>
        <DialogDescription>
          Members get access to every page and folder in the space, including
          ones added later.
        </DialogDescription>
      </DialogHeader>
      <div className="flex max-h-[70vh] flex-col gap-4 overflow-y-auto">
        {/* Nothing is drawn until we know whether this person may share at all:
            mounting the address field and then replacing it would take the
            focus (and the half-typed address) away from anyone quick. */}
        {namespace.isPending && <Skeleton className="h-9 w-full" />}
        {!namespace.isPending && canShare && (
          <ShareComposer
            recipients={recipients}
            roles={NS_ROLES}
            role={role}
            onRoleChange={(r) => setRole(r as NamespaceRole)}
            message={message}
            onMessageChange={setMessage}
            subject="space"
            onSubmit={() => share.mutate()}
            submitting={share.isPending}
            blocked={atLimit}
          />
        )}

        {result && (
          <ShareOutcome
            shared={result.shared ?? []}
            invited={result.invited ?? []}
            skipped={result.skipped ?? []}
            subject="space"
          />
        )}

        <ShareCounter
          used={used}
          limit={limit}
          atLimitMessage={`This space has reached its limit of ${limit} ${plural(
            limit ?? 0,
            "person",
            "people",
          )}. Remove someone to add anybody else.`}
        />

        <AccessList
          roles={NS_ROLES}
          rows={members.data?.data.map((m) => ({
            user: m.user,
            role: m.role,
            isOwner: m.is_owner,
          }))}
          isPending={members.isPending || invitations.isPending}
          onUpdateRole={(userId, role_) =>
            update.mutate({ userId, role: role_ })
          }
          onRemove={(userId) => remove.mutate(userId)}
          removing={remove.isPending}
          canManage={canShare}
          invitations={invitations.data ?? []}
          onWithdraw={canShare ? (id) => withdraw.mutate(id) : undefined}
          withdrawing={withdraw.isPending}
        />
      </div>
    </>
  )
}

// --- pages --------------------------------------------------------------------

function DocumentShare({
  target,
}: {
  target: Extract<DialogTarget, { type: "document" }>
}) {
  const queryClient = useQueryClient()
  const { user: me } = useAuth()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const namespace = useQuery(namespaceQuery(target.namespaceId))
  const ns = namespace.data
  // The backend grants sharing to space editors only — a shared-only editor is
  // refused with a 403. Hiding the controls says the same thing up front.
  const canShare = canEditNamespace(ns)

  const shares = useQuery(documentSharesQuery(target.id))
  const invitations = useQuery(documentInvitationsQuery(target.id))

  const [role, setRole] = useState<ShareRole>("viewer")
  const [message, setMessage] = useState("")
  const [result, setResult] = useState<ShareResult | null>(null)
  const recipients = useRecipients(() => setResult(null))

  const used = (shares.data?.data.length ?? 0) + (invitations.data?.length ?? 0)
  // The ceiling belongs to the space owner; the reply to a share is the only
  // place it is stated, so fall back to our own until one comes back.
  const limit = result?.max_recipients ?? me?.max_shares_per_document ?? null
  const atLimit = limit !== null && used >= limit

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.documents.shares(target.id),
    })
    queryClient.invalidateQueries({
      queryKey: queryKeys.documents.invitations(target.id),
    })
    queryClient.invalidateQueries({ queryKey: queryKeys.shared })
  }

  const share = useMutation({
    mutationFn: async () =>
      (
        await DocumentsService.shareDocumentWithMany({
          path: { document_id: target.id },
          body: {
            emails: recipients.valid,
            role,
            message: message.trim() || null,
          },
        })
      ).data,
    onSuccess: (data) => {
      setResult(data)
      recipients.clear()
      setMessage("")
      invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })

  const update = useMutation({
    mutationFn: (v: { userId: string; role: string }) =>
      DocumentsService.updateDocumentShare({
        path: { document_id: target.id, user_id: v.userId },
        body: { role: v.role as ShareRole },
      }),
    onSuccess: invalidate,
    onError: (e) => {
      handleError.call(showErrorToast, e)
      invalidate()
    },
  })
  const remove = useMutation({
    mutationFn: (userId: string) =>
      DocumentsService.unshareDocument({
        path: { document_id: target.id, user_id: userId },
      }),
    onSuccess: () => {
      showSuccessToast("Access removed")
      invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const withdraw = useMutation({
    mutationFn: (invitationId: string) =>
      DocumentsService.cancelInvitation({
        path: { document_id: target.id, invitation_id: invitationId },
      }),
    onSuccess: () => {
      showSuccessToast("Invitation withdrawn")
      invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <>
      <DialogHeader>
        <DialogTitle>Share “{target.title}”</DialogTitle>
        <DialogDescription>
          Give specific people access to this page only.
        </DialogDescription>
      </DialogHeader>
      <div className="flex max-h-[70vh] flex-col gap-4 overflow-y-auto">
        {namespace.isPending && <Skeleton className="h-9 w-full" />}
        {!namespace.isPending && canShare && (
          <ShareComposer
            recipients={recipients}
            roles={DOC_ROLES}
            role={role}
            onRoleChange={(r) => setRole(r as ShareRole)}
            message={message}
            onMessageChange={setMessage}
            subject="page"
            onSubmit={() => share.mutate()}
            submitting={share.isPending}
            blocked={atLimit}
          />
        )}

        {result && (
          <ShareOutcome
            shared={result.shared ?? []}
            invited={result.invited ?? []}
            skipped={result.skipped ?? []}
            subject="page"
          />
        )}

        {ns && (
          <p className="rounded-md bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
            Everyone in the space{" "}
            <span className="font-medium text-foreground">{ns.name}</span>{" "}
            already has access according to their space role
            {ns.member_count
              ? ` (${ns.member_count} ${plural(ns.member_count, "member", "members")})`
              : ""}
            . Shares below add people from outside the space.
          </p>
        )}

        <ShareCounter
          used={used}
          limit={limit}
          atLimitMessage={`This page has reached its limit of ${limit} people. Remove someone, or share it by link instead.`}
        />

        <AccessList
          roles={DOC_ROLES}
          rows={shares.data?.data.map((s) => ({ user: s.user, role: s.role }))}
          isPending={shares.isPending || invitations.isPending}
          onUpdateRole={(userId, role_) =>
            update.mutate({ userId, role: role_ })
          }
          onRemove={(userId) => remove.mutate(userId)}
          removing={remove.isPending}
          canManage={canShare}
          invitations={invitations.data ?? []}
          onWithdraw={canShare ? (id) => withdraw.mutate(id) : undefined}
          withdrawing={withdraw.isPending}
        />

        {canShare && <PublicLinkSection documentId={target.id} />}
      </div>
    </>
  )
}

interface ShareDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  target: Extract<DialogTarget, { type: "document" | "namespace" }>
}

export function ShareDialog({ open, onOpenChange, target }: ShareDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg" data-testid="share-dialog">
        {target.type === "document" ? (
          <DocumentShare target={target} />
        ) : (
          <NamespaceShare target={target} />
        )}
      </DialogContent>
    </Dialog>
  )
}
