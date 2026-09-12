import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import { createFileRoute, Link as RouterLink } from "@tanstack/react-router"
import { MailCheck } from "lucide-react"
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
import { extractErrorMessage } from "@/utils"

const formSchema = z.object({
  email: z.email({ message: "Invalid email address" }),
})

type FormData = z.infer<typeof formSchema>

export const Route = createFileRoute("/forgot-password")({
  component: ForgotPassword,
  head: () => ({
    meta: [
      {
        title: "Forgot your password - PlusGPT",
      },
    ],
  }),
})

function ForgotPassword() {
  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    defaultValues: { email: "" },
  })

  const recover = useMutation({
    mutationFn: async (data: FormData) =>
      (await LoginService.recoverPassword({ body: data })).data,
  })

  // The reply is the same for an address with an account and one without, so
  // this screen must not hint at which it was — only the mailbox learns that.
  if (recover.isSuccess) {
    return (
      <AuthLayout>
        <div className="flex flex-col gap-6" data-testid="recovery-sent">
          <div className="flex flex-col items-center gap-2 text-center">
            <MailCheck className="size-8 text-muted-foreground" />
            <h1 className="text-2xl font-bold">Check your inbox</h1>
            <p className="text-sm text-muted-foreground">
              {recover.data.message}
            </p>
          </div>
          <div className="text-center text-sm">
            <RouterLink to="/login" className="underline underline-offset-4">
              Back to login
            </RouterLink>
          </div>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit((data) => recover.mutate(data))}
          className="flex flex-col gap-6"
        >
          <div className="flex flex-col items-center gap-2 text-center">
            <h1 className="text-2xl font-bold">Forgot your password?</h1>
            <p className="text-sm text-muted-foreground">
              We will email you a link for choosing a new one.
            </p>
          </div>

          {recover.error && (
            <AuthAlert>{extractErrorMessage(recover.error)}</AuthAlert>
          )}

          <div className="grid gap-4">
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

            <LoadingButton type="submit" loading={recover.isPending}>
              Send the link
            </LoadingButton>
          </div>

          <div className="text-center text-sm">
            <RouterLink to="/login" className="underline underline-offset-4">
              Back to login
            </RouterLink>
          </div>
        </form>
      </Form>
    </AuthLayout>
  )
}
