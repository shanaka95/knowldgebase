import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
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
import { LoadingButton } from "@/components/ui/loading-button"
import { PasswordInput } from "@/components/ui/password-input"
import { extractErrorMessage } from "@/utils"

const formSchema = z
  .object({
    new_password: z
      .string()
      .min(1, { message: "Password is required" })
      .min(8, { message: "Password must be at least 8 characters" }),
    confirm_password: z
      .string()
      .min(1, { message: "Password confirmation is required" }),
  })
  .refine((data) => data.new_password === data.confirm_password, {
    message: "The passwords don't match",
    path: ["confirm_password"],
  })

type FormData = z.infer<typeof formSchema>

export const Route = createFileRoute("/reset-password")({
  component: ResetPassword,
  validateSearch: z.object({
    token: z.string().optional().catch(undefined),
  }),
  head: () => ({
    meta: [
      {
        title: "Choose a new password - PlusGPT",
      },
    ],
  }),
})

function ResetPassword() {
  const { token } = Route.useSearch()
  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: { new_password: "", confirm_password: "" },
  })

  const reset = useMutation({
    mutationFn: async (data: FormData) =>
      (
        await LoginService.resetPassword({
          body: { token: token as string, new_password: data.new_password },
        })
      ).data,
  })

  if (reset.isSuccess) {
    return (
      <AuthLayout>
        <div className="flex flex-col gap-6" data-testid="reset-success">
          <div className="flex flex-col items-center gap-2 text-center">
            <CircleCheck className="size-8 text-muted-foreground" />
            <h1 className="text-2xl font-bold">Password changed</h1>
            <p className="text-sm text-muted-foreground">
              {reset.data.message}
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
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit((data) => reset.mutate(data))}
          className="flex flex-col gap-6"
        >
          <div className="flex flex-col items-center gap-2 text-center">
            <h1 className="text-2xl font-bold">Choose a new password</h1>
            <p className="text-sm text-muted-foreground">
              Setting it ends every other session on your account.
            </p>
          </div>

          {!token && (
            <AuthAlert>
              This reset link is missing its token. Ask for a new one.
            </AuthAlert>
          )}
          {reset.error && (
            <AuthAlert>{extractErrorMessage(reset.error)}</AuthAlert>
          )}

          <div className="grid gap-4">
            <FormField
              control={form.control}
              name="new_password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>New Password</FormLabel>
                  <FormControl>
                    <PasswordInput
                      data-testid="new-password-input"
                      placeholder="••••••••"
                      autoComplete="new-password"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage className="text-xs" />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="confirm_password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Confirm Password</FormLabel>
                  <FormControl>
                    <PasswordInput
                      data-testid="confirm-password-input"
                      placeholder="••••••••"
                      autoComplete="new-password"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage className="text-xs" />
                </FormItem>
              )}
            />

            <LoadingButton
              type="submit"
              loading={reset.isPending}
              disabled={!token}
            >
              Set the new password
            </LoadingButton>
          </div>

          <div className="text-center text-sm">
            <RouterLink
              to="/forgot-password"
              className="underline underline-offset-4"
            >
              Ask for a new link
            </RouterLink>
          </div>
        </form>
      </Form>
    </AuthLayout>
  )
}
