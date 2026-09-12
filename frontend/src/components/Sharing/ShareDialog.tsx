import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Crown, Trash2, UserPlus } from "lucide-react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import {
  DocumentsService,
  type NamespaceRole,
  NamespacesService,
  type ShareRole,
  type UserRef,
} from "@/client"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
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
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { queryKeys } from "@/lib/queryKeys"
import { namespaceMembersQuery, namespaceQuery } from "@/queries/namespaces"
import type { DialogTarget } from "@/stores/dialogs"
import { getInitials, handleError } from "@/utils"

const schema = z.object({
  email: z.email({ message: "Enter a valid e-mail address" }),
  role: z.string(),
})
type FormData = z.infer<typeof schema>

interface ShareRow {
  user: UserRef
  role: string
  isOwner?: boolean
}

interface RoleOption {
  value: string
  label: string
  hint: string
}

interface Adapter {
  title: string
  description: string
  roles: RoleOption[]
  add: (email: string, role: string) => Promise<unknown>
  update: (userId: string, role: string) => Promise<unknown>
  remove: (userId: string) => Promise<unknown>
  invalidate: () => void
  note?: React.ReactNode
}

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

function ShareBody({
  adapter,
  rows,
  isPending,
}: {
  adapter: Adapter
  rows: ShareRow[] | undefined
  isPending: boolean
}) {
  const { user: me } = useAuth()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", role: adapter.roles[0].value },
  })

  const add = useMutation({
    mutationFn: (d: FormData) => adapter.add(d.email, d.role),
    onSuccess: () => {
      showSuccessToast("Access granted")
      form.reset({ email: "", role: form.getValues("role") })
      adapter.invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const update = useMutation({
    mutationFn: (v: { userId: string; role: string }) =>
      adapter.update(v.userId, v.role),
    onSuccess: () => adapter.invalidate(),
    onError: (e) => {
      handleError.call(showErrorToast, e)
      adapter.invalidate()
    },
  })
  const remove = useMutation({
    mutationFn: (userId: string) => adapter.remove(userId),
    onSuccess: () => {
      showSuccessToast("Access removed")
      adapter.invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
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
                    {adapter.roles.map((r) => (
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

      {adapter.note}

      <div className="flex flex-col divide-y rounded-md border">
        {isPending && (
          <div className="flex flex-col gap-3 p-3">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </div>
        )}
        {!isPending && (rows?.length ?? 0) === 0 && (
          <p className="p-4 text-center text-sm text-muted-foreground">
            Nobody has been added yet.
          </p>
        )}
        {rows?.map((row) => {
          const isMe = row.user.id === me?.id
          return (
            <div
              key={row.user.id}
              className="flex items-center gap-3 px-3 py-2"
              data-testid="share-row"
            >
              <Avatar className="size-8">
                <AvatarFallback className="text-xs">
                  {getInitials(row.user.full_name || row.user.email)}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">
                  {row.user.full_name || row.user.email}
                  {isMe && (
                    <span className="text-muted-foreground"> (you)</span>
                  )}
                </p>
                {row.user.full_name && (
                  <p className="truncate text-xs text-muted-foreground">
                    {row.user.email}
                  </p>
                )}
              </div>
              {row.isOwner ? (
                <span className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground">
                  <Crown className="size-3.5" />
                  Owner
                </span>
              ) : (
                <>
                  <Select
                    value={row.role}
                    onValueChange={(role) =>
                      update.mutate({ userId: row.user.id, role })
                    }
                  >
                    <SelectTrigger
                      className="h-8 w-32 text-xs"
                      aria-label="Role"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {adapter.roles.map((r) => (
                        <SelectItem key={r.value} value={r.value}>
                          <span className="flex flex-col items-start">
                            <span>{r.label}</span>
                            <span className="text-xs text-muted-foreground">
                              {r.hint}
                            </span>
                          </span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Remove ${row.user.email}`}
                    onClick={() => remove.mutate(row.user.id)}
                    disabled={remove.isPending}
                  >
                    <Trash2 className="size-4 text-muted-foreground" />
                  </Button>
                </>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function DocumentShare({
  target,
}: {
  target: Extract<DialogTarget, { type: "document" }>
}) {
  const queryClient = useQueryClient()
  const { data: ns } = useQuery(namespaceQuery(target.namespaceId))
  const shares = useQuery({
    queryKey: queryKeys.documents.shares(target.id),
    queryFn: async () =>
      (
        await DocumentsService.readDocumentShares({
          path: { document_id: target.id },
        })
      ).data,
  })
  const rows = shares.data?.data.map((s) => ({ user: s.user, role: s.role }))

  const adapter: Adapter = {
    title: `Share “${target.title}”`,
    description: "Give specific people access to this page only.",
    roles: DOC_ROLES,
    add: (email, role) =>
      DocumentsService.shareDocument({
        path: { document_id: target.id },
        body: { email, role: role as ShareRole },
      }),
    update: (userId, role) =>
      DocumentsService.updateDocumentShare({
        path: { document_id: target.id, user_id: userId },
        body: { role: role as ShareRole },
      }),
    remove: (userId) =>
      DocumentsService.unshareDocument({
        path: { document_id: target.id, user_id: userId },
      }),
    invalidate: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.documents.shares(target.id),
      })
      queryClient.invalidateQueries({ queryKey: queryKeys.shared })
    },
    note: ns ? (
      <p className="rounded-md bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
        Everyone in the space{" "}
        <span className="font-medium text-foreground">{ns.name}</span> already
        has access according to their space role
        {ns.member_count
          ? ` (${ns.member_count} member${ns.member_count === 1 ? "" : "s"})`
          : ""}
        . Shares below add people from outside the space.
      </p>
    ) : null,
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{adapter.title}</DialogTitle>
        <DialogDescription>{adapter.description}</DialogDescription>
      </DialogHeader>
      <ShareBody adapter={adapter} rows={rows} isPending={shares.isPending} />
    </>
  )
}

function NamespaceShare({
  target,
}: {
  target: Extract<DialogTarget, { type: "namespace" }>
}) {
  const queryClient = useQueryClient()
  const members = useQuery(namespaceMembersQuery(target.id))
  const rows = members.data?.data.map((m) => ({
    user: m.user,
    role: m.role,
    isOwner: m.is_owner,
  }))

  const adapter: Adapter = {
    title: `Share space “${target.name}”`,
    description: "Members get access to every page and folder in the space.",
    roles: NS_ROLES,
    add: (email, role) =>
      NamespacesService.addNamespaceMember({
        path: { namespace_id: target.id },
        body: { email, role: role as NamespaceRole },
      }),
    update: (userId, role) =>
      NamespacesService.updateNamespaceMember({
        path: { namespace_id: target.id, user_id: userId },
        body: { role: role as NamespaceRole },
      }),
    remove: (userId) =>
      NamespacesService.removeNamespaceMember({
        path: { namespace_id: target.id, user_id: userId },
      }),
    invalidate: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.namespaces.members(target.id),
      })
      queryClient.invalidateQueries({ queryKey: queryKeys.namespaces.all })
      queryClient.invalidateQueries({ queryKey: queryKeys.shared })
    },
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{adapter.title}</DialogTitle>
        <DialogDescription>{adapter.description}</DialogDescription>
      </DialogHeader>
      <ShareBody adapter={adapter} rows={rows} isPending={members.isPending} />
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
