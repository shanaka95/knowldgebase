import { zodResolver } from "@hookform/resolvers/zod"
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { Send, UserPlus } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import {
  DocumentsService,
  type NamespaceRole,
  NamespacesService,
  type ShareResult,
  type ShareRole,
} from "@/client"
import { APP_NAME } from "@/components/Common/Logo"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { useDebouncedValue } from "@/hooks/useDebouncedValue"
import { canEditNamespace } from "@/hooks/useNamespaces"
import { queryKeys } from "@/lib/queryKeys"
import { namespaceMembersQuery, namespaceQuery } from "@/queries/namespaces"
import {
  documentInvitationsQuery,
  documentSharesQuery,
  userLookupQuery,
} from "@/queries/sharing"
import type { DialogTarget } from "@/stores/dialogs"
import { handleError } from "@/utils"
import { AccessList, type RoleOption } from "./AccessList"
import {
  type ChipLookup,
  EmailChipsInput,
  isCompleteEmail,
} from "./EmailChipsInput"
import { PublicLinkSection } from "./PublicLinkSection"

const MESSAGE_MAX = 1000
/** The batch endpoint accepts at most this many addresses in one call. */
const BATCH_MAX = 50

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

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)

// --- spaces -------------------------------------------------------------------

const namespaceSchema = z.object({
  email: z.email({ message: "Enter a valid e-mail address" }),
  role: z.string(),
})
type NamespaceFormData = z.infer<typeof namespaceSchema>

function NamespaceShare({
  target,
}: {
  target: Extract<DialogTarget, { type: "namespace" }>
}) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const members = useQuery(namespaceMembersQuery(target.id))
  const rows = members.data?.data.map((m) => ({
    user: m.user,
    role: m.role,
    isOwner: m.is_owner,
  }))

  const form = useForm<NamespaceFormData>({
    resolver: zodResolver(namespaceSchema),
    defaultValues: { email: "", role: NS_ROLES[0].value },
  })

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.namespaces.members(target.id),
    })
    queryClient.invalidateQueries({ queryKey: queryKeys.namespaces.all })
    queryClient.invalidateQueries({ queryKey: queryKeys.shared })
  }

  const add = useMutation({
    mutationFn: (d: NamespaceFormData) =>
      NamespacesService.addNamespaceMember({
        path: { namespace_id: target.id },
        body: { email: d.email, role: d.role as NamespaceRole },
      }),
    onSuccess: () => {
      showSuccessToast("Access granted")
      form.reset({ email: "", role: form.getValues("role") })
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

  return (
    <>
      <DialogHeader>
        <DialogTitle>Share space “{target.name}”</DialogTitle>
        <DialogDescription>
          Members get access to every page and folder in the space.
        </DialogDescription>
      </DialogHeader>
      <div className="flex flex-col gap-4">
        <Form {...form}>
          <form
            onSubmit={form.handleSubmit((d) => add.mutate(d))}
            className="flex flex-col gap-2 sm:flex-row sm:items-start"
          >
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem className="flex-1">
                  <FormControl>
                    <Input
                      type="email"
                      placeholder="colleague@company.com"
                      autoFocus
                      data-testid="share-email"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="role"
              render={({ field }) => (
                <FormItem>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger
                        className="w-full sm:w-36"
                        data-testid="share-role"
                      >
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {NS_ROLES.map((r) => (
                        <SelectItem key={r.value} value={r.value}>
                          {r.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormItem>
              )}
            />
            <LoadingButton
              type="submit"
              loading={add.isPending}
              data-testid="share-submit"
            >
              <UserPlus />
              Invite
            </LoadingButton>
          </form>
        </Form>

        <AccessList
          roles={NS_ROLES}
          rows={rows}
          isPending={members.isPending}
          onUpdateRole={(userId, role) => update.mutate({ userId, role })}
          onRemove={(userId) => remove.mutate(userId)}
          removing={remove.isPending}
        />
      </div>
    </>
  )
}

// --- pages --------------------------------------------------------------------

function ShareOutcome({ result }: { result: ShareResult }) {
  const shared = result.shared ?? []
  const invited = result.invited ?? []
  const skipped = result.skipped ?? []

  return (
    <div
      className="flex flex-col gap-2 rounded-md border bg-muted/40 p-3 text-xs"
      data-testid="share-result"
    >
      {shared.length > 0 && (
        <p>
          <span className="font-medium text-foreground">
            {shared.length} {plural(shared.length, "person", "people")} now{" "}
            {plural(shared.length, "has", "have")} access
          </span>{" "}
          — {shared.map((s) => s.user.email).join(", ")}
        </p>
      )}
      {invited.length > 0 && (
        <p>
          <span className="font-medium text-foreground">
            {invited.length}{" "}
            {plural(invited.length, "invitation", "invitations")} sent
          </span>{" "}
          — {invited.map((i) => i.email).join(", ")}. The page opens for them as
          soon as they create an account on that address and confirm it.
        </p>
      )}
      {skipped.length > 0 && (
        <ul className="flex flex-col gap-1" data-testid="share-skipped">
          {skipped.map((s) => (
            <li key={s.email} className="text-muted-foreground">
              <span className="font-medium text-foreground">{s.email}</span> —{" "}
              {s.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function DocumentShare({
  target,
}: {
  target: Extract<DialogTarget, { type: "document" }>
}) {
  const queryClient = useQueryClient()
  const { user: me } = useAuth()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const { data: ns } = useQuery(namespaceQuery(target.namespaceId))
  // The backend grants sharing to space editors only — a shared-only editor is
  // refused with a 403. Hiding the controls says the same thing up front.
  const canShare = canEditNamespace(ns)

  const shares = useQuery(documentSharesQuery(target.id))
  const invitations = useQuery(documentInvitationsQuery(target.id))

  const [emails, setEmails] = useState<string[]>([])
  const [role, setRole] = useState<ShareRole>("viewer")
  const [message, setMessage] = useState("")
  const [result, setResult] = useState<ShareResult | null>(null)

  const valid = emails.filter(isCompleteEmail)
  const invalid = emails.filter((e) => !isCompleteEmail(e))

  // Debounced on a joined key rather than the array, whose identity changes on
  // every render and would restart the timer forever.
  const debouncedKey = useDebouncedValue(valid.join(","), 250)
  const lookupEmails = debouncedKey ? debouncedKey.split(",") : []
  const lookupResults = useQueries({
    queries: lookupEmails.map((email) => userLookupQuery(email)),
  })

  const lookups = new Map<string, ChipLookup>()
  for (const email of emails) {
    if (!isCompleteEmail(email)) {
      lookups.set(email, { status: "invalid" })
      continue
    }
    const index = lookupEmails.indexOf(email)
    const lookup = index >= 0 ? lookupResults[index] : undefined
    if (!lookup || lookup.isPending) {
      lookups.set(email, { status: "pending" })
    } else if (lookup.isError) {
      // We could not find out; say nothing rather than guess.
      lookups.set(email, { status: "unknown" })
    } else if (lookup.data?.exists) {
      lookups.set(email, { status: "known", user: lookup.data.user })
    } else {
      lookups.set(email, { status: "new" })
    }
  }
  const newcomers = [...lookups.values()].filter(
    (l) => l.status === "new",
  ).length

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
            emails: valid,
            role,
            message: message.trim() || null,
          },
        })
      ).data,
    onSuccess: (data) => {
      setResult(data)
      setEmails([])
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

  const tooMany = valid.length > BATCH_MAX
  const canSubmit =
    valid.length > 0 && invalid.length === 0 && !tooMany && !atLimit

  return (
    <>
      <DialogHeader>
        <DialogTitle>Share “{target.title}”</DialogTitle>
        <DialogDescription>
          Give specific people access to this page only.
        </DialogDescription>
      </DialogHeader>
      <div className="flex max-h-[70vh] flex-col gap-4 overflow-y-auto">
        {canShare && (
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (canSubmit && !share.isPending) share.mutate()
            }}
          >
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
              <div className="flex-1">
                <EmailChipsInput
                  emails={emails}
                  onChange={(next) => {
                    setEmails(next)
                    setResult(null)
                  }}
                  lookups={lookups}
                  disabled={share.isPending}
                  data-testid="share-email"
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  Type an address and press Enter or comma to add it.
                </p>
              </div>
              <Select
                value={role}
                onValueChange={(v) => setRole(v as ShareRole)}
              >
                <SelectTrigger
                  className="w-full sm:w-36"
                  data-testid="share-role"
                  aria-label="Access level"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DOC_ROLES.map((r) => (
                    <SelectItem key={r.value} value={r.value}>
                      {r.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <LoadingButton
                type="submit"
                loading={share.isPending}
                disabled={!canSubmit}
                data-testid="share-submit"
              >
                <Send />
                Share
              </LoadingButton>
            </div>

            {invalid.length > 0 && (
              <p
                className="text-xs text-destructive"
                data-testid="share-invalid"
              >
                {invalid.join(", ")} {plural(invalid.length, "is", "are")} not a
                valid e-mail address. Remove{" "}
                {plural(invalid.length, "it", "them")} to continue.
              </p>
            )}
            {tooMany && (
              <p className="text-xs text-destructive">
                Share with at most {BATCH_MAX} addresses at a time.
              </p>
            )}
            {newcomers > 0 && (
              <p
                className="rounded-md bg-muted/60 px-3 py-2 text-xs text-muted-foreground"
                data-testid="share-invite-notice"
              >
                {newcomers} of these addresses{" "}
                {plural(newcomers, "doesn't", "don't")} have a {APP_NAME}{" "}
                account yet. They'll get an email inviting them to create one,
                and the page opens as soon as they confirm it.
              </p>
            )}

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="share-message" className="text-xs font-normal">
                Add a message
              </Label>
              <Textarea
                id="share-message"
                rows={2}
                maxLength={MESSAGE_MAX}
                placeholder="Optional — included in the email."
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                data-testid="share-message"
              />
              {message.length > 0 && (
                <p className="self-end text-[11px] text-muted-foreground">
                  {message.length}/{MESSAGE_MAX}
                </p>
              )}
            </div>
          </form>
        )}

        {result && <ShareOutcome result={result} />}

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

        <div className="flex items-center justify-between gap-2">
          <span
            className="text-xs text-muted-foreground"
            data-testid="share-recipients"
          >
            {limit === null
              ? `${used} ${plural(used, "person", "people")}`
              : `${used} of ${limit} ${plural(limit, "person", "people")}`}
          </span>
          {atLimit && (
            <span
              className="text-xs text-destructive"
              data-testid="share-limit-reason"
            >
              This page has reached its limit of {limit} people. Remove someone,
              or share it by link instead.
            </span>
          )}
        </div>

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
