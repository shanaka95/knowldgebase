import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute, Link as RouterLink } from "@tanstack/react-router"
import { CircleCheck } from "lucide-react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { LoginService } from "@/client"
import { AuthAlert } from "@/components/Common/AuthAlert"
import { AuthLayout } from "@/components/Common/AuthLayout"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { Spinner } from "@/components/ui/spinner"
import { extractErrorMessage } from "@/utils"

const emailSchema = z.object({
  email: z.email({ message: "Invalid email address" }),
})

type EmailForm = z.infer<typeof emailSchema>

export const Route = createFileRoute("/verify-email")({
  component: VerifyEmail,
  validateSearch: z.object({
    token: z.string().optional().catch(undefined),
  }),
  head: () => ({
    meta: [
      {
        title: "Confirm your email - PlusGPT",
      },
    ],
  }),
})

function VerifyEmail() {
  const { token } = Route.useSearch()

  // The link can only be spent once, so this must not be refetched behind the
  // user's back: a second attempt would report a perfectly good link as used.
  const confirmation = useQuery({
    queryKey: ["verify-email", token],
    queryFn: async () =>
      (await LoginService.verifyEmail({ body: { token: token as string } }))
        .data,
    enabled: Boolean(token),
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
    refetchOnMount: false,
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
  })

  if (token && confirmation.isPending) {
    return (
      <AuthLayout>
        <div
          className="flex flex-col items-center gap-3 text-center"
          data-testid="verify-email-pending"
        >
          <Spinner className="size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Confirming your address…
          </p>
        </div>
      </AuthLayout>
    )
  }

  if (confirmation.isSuccess) {
    return (
      <AuthLayout>
        <div className="flex flex-col gap-6" data-testid="verify-email-success">
          <div className="flex flex-col items-center gap-2 text-center">
            <CircleCheck className="size-8 text-muted-foreground" />
            <h1 className="text-2xl font-bold">Address confirmed</h1>
            <p className="text-sm text-muted-foreground">
              {confirmation.data.message}
            </p>
          </div>
          <div className="text-center text-sm">
            <RouterLink to="/login" className="underline underline-offset-4">
              Log in
            </RouterLink>
          </div>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout>
      <div className="flex flex-col gap-6" data-testid="verify-email-failed">
        <div className="flex flex-col items-center gap-2 text-center">
          <h1 className="text-2xl font-bold">That link did not work</h1>
        </div>

        <AuthAlert>
          {confirmation.error
            ? extractErrorMessage(confirmation.error)
            : "This confirmation link is missing its token. Ask for a new one."}
        </AuthAlert>

        <ResendVerification />

        <div className="text-center text-sm">
          <RouterLink to="/login" className="underline underline-offset-4">
            Back to login
          </RouterLink>
        </div>
      </div>
    </AuthLayout>
  )
}

function ResendVerification() {
  const form = useForm<EmailForm>({
    resolver: zodResolver(emailSchema),
    mode: "onBlur",
    defaultValues: { email: "" },
  })

  const resend = useMutation({
    mutationFn: async (data: EmailForm) =>
      (await LoginService.resendVerification({ body: data })).data,
  })

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit((data) => resend.mutate(data))}
        className="grid gap-4"
      >
        {resend.data && (
          <AuthAlert tone="info">{resend.data.message}</AuthAlert>
        )}
        {resend.error && (
          <AuthAlert>{extractErrorMessage(resend.error)}</AuthAlert>
        )}

        <FormField
          control={form.control}
          name="email"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Email</FormLabel>
              <FormControl>
                <Input
                  data-testid="email-input"
                  placeholder="user@example.com"
                  type="email"
                  autoComplete="email"
                  {...field}
                />
              </FormControl>
              <FormMessage className="text-xs" />
            </FormItem>
          )}
        />

        <LoadingButton
          type="submit"
          loading={resend.isPending}
          data-testid="resend-confirmation"
        >
          Send a new link
        </LoadingButton>
      </form>
    </Form>
  )
}
