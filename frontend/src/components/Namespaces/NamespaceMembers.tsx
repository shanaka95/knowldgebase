import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Crown, Trash2, UserPlus } from "lucide-react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import {
  type NamespacePublic,
  type NamespaceRole,
  NamespacesService,
} from "@/client"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
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
import { namespaceMembersQuery } from "@/queries/namespaces"
import { getInitials, handleError } from "@/utils"

const ROLES: { value: NamespaceRole; label: string; hint: string }[] = [
  { value: "viewer", label: "Viewer", hint: "Can read every page" },
  { value: "editor", label: "Editor", hint: "Can create and edit pages" },
  { value: "admin", label: "Admin", hint: "Can manage members and settings" },
]

const schema = z.object({
  email: z.email({ message: "Enter a valid e-mail address" }),
  role: z.enum(["viewer", "editor", "admin"]),
})
type FormData = z.infer<typeof schema>

export function NamespaceMembers({
  namespace,
}: {
  namespace: NamespacePublic
}) {
  const queryClient = useQueryClient()
  const { user: me } = useAuth()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { data, isPending } = useQuery(namespaceMembersQuery(namespace.id))

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.namespaces.members(namespace.id),
    })
    queryClient.invalidateQueries({ queryKey: queryKeys.namespaces.all })
  }

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", role: "viewer" },
  })

  const add = useMutation({
    mutationFn: (d: FormData) =>
      NamespacesService.addNamespaceMember({
        path: { namespace_id: namespace.id },
        body: { email: d.email, role: d.role },
      }),
    onSuccess: () => {
      showSuccessToast("Member added")
      form.reset({ email: "", role: form.getValues("role") })
      invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const update = useMutation({
    mutationFn: (v: { userId: string; role: NamespaceRole }) =>
      NamespacesService.updateNamespaceMember({
        path: { namespace_id: namespace.id, user_id: v.userId },
        body: { role: v.role },
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
        path: { namespace_id: namespace.id, user_id: userId },
      }),
    onSuccess: () => {
      showSuccessToast("Member removed")
      invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Members</CardTitle>
        <CardDescription>
          People with access to every page in this space. Add someone by their
          account e-mail.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
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
                      data-testid="member-email"
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
                        className="w-full sm:w-32"
                        data-testid="member-role"
                      >
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {ROLES.map((r) => (
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
              data-testid="member-add"
            >
              <UserPlus />
              Add
            </LoadingButton>
          </form>
        </Form>

        <div className="divide-y rounded-md border">
          {isPending && (
            <div className="flex flex-col gap-3 p-3">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          )}
          {data?.data.map((m) => {
            const isMe = m.user.id === me?.id
            return (
              <div
                key={m.user.id}
                className="flex items-center gap-3 px-3 py-2"
                data-testid="member-row"
              >
                <Avatar className="size-8">
                  <AvatarFallback className="text-xs">
                    {getInitials(m.user.full_name || m.user.email)}
                  </AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">
                    {m.user.full_name || m.user.email}
                    {isMe && (
                      <span className="text-muted-foreground"> (you)</span>
                    )}
                  </p>
                  {m.user.full_name && (
                    <p className="truncate text-xs text-muted-foreground">
                      {m.user.email}
                    </p>
                  )}
                </div>
                {m.is_owner ? (
                  <span className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground">
                    <Crown className="size-3.5" />
                    Owner
                  </span>
                ) : (
                  <>
                    <Select
                      value={m.role}
                      onValueChange={(role) =>
                        update.mutate({
                          userId: m.user.id,
                          role: role as NamespaceRole,
                        })
                      }
                    >
                      <SelectTrigger
                        className="h-8 w-32 text-xs"
                        aria-label="Role"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {ROLES.map((r) => (
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
                      aria-label={`Remove ${m.user.email}`}
                      onClick={() => remove.mutate(m.user.id)}
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
      </CardContent>
    </Card>
  )
}
