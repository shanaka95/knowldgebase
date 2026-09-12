import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import {
  createFileRoute,
  Link as RouterLink,
  redirect,
} from "@tanstack/react-router"
import { MailCheck } from "lucide-react"
import { useForm } from "react-hook-form"
import { z } from "zod"
import { LoginService } from "@/client"
import { AuthAlert } from "@/components/Common/AuthAlert"
import { AuthLayout } from "@/components/Common/AuthLayout"
import { Button } from "@/components/ui/button"
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
import { PasswordInput } from "@/components/ui/password-input"
import useAuth, { isLoggedIn } from "@/hooks/useAuth"
import { extractErrorMessage } from "@/utils"

const formSchema = z
  .object({
    email: z.email({ message: "Invalid email address" }),
    full_name: z.string().min(1, { message: "Full Name is required" }),
    password: z
      .string()
      .min(1, { message: "Password is required" })
      .min(8, { message: "Password must be at least 8 characters" }),
    confirm_password: z
      .string()
      .min(1, { message: "Password confirmation is required" }),
  })
  .refine((data) => data.password === data.confirm_password, {
    message: "The passwords don't match",
    path: ["confirm_password"],
  })

type FormData = z.infer<typeof formSchema>

export const Route = createFileRoute("/signup")({
  component: SignUp,
  // An invitation already names the address it was sent to, and access only
  // follows that address, so it arrives prefilled rather than retyped.
  validateSearch: z.object({
    email: z.string().optional().catch(undefined),
  }),
  beforeLoad: async () => {
    if (isLoggedIn()) {
      throw redirect({
        to: "/",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: "Sign Up - PlusGPT",
      },
    ],
  }),
})

function SignUp() {
  const { signUpMutation } = useAuth()
  const { email: invitedEmail } = Route.useSearch()
  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      email: invitedEmail ?? "",
      full_name: "",
      password: "",
      confirm_password: "",
    },
  })

  const onSubmit = (data: FormData) => {
    if (signUpMutation.isPending) return

    // exclude confirm_password from submission data
    const { confirm_password: _confirm_password, ...submitData } = data
    signUpMutation.mutate(submitData)
  }

  // Registering never signs anyone in: the account cannot be used until the
  // address has been confirmed, which is the whole point of the link.
  if (signUpMutation.isSuccess) {
    return (
      <AuthLayout>
        <CheckYourInbox
          email={form.getValues("email")}
          message={signUpMutation.data.message}
        />
      </AuthLayout>
    )
  }

  return (
    <AuthLayout>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex flex-col gap-6"
        >
          <div className="flex flex-col items-center gap-2 text-center">
            <h1 className="text-2xl font-bold">Create an account</h1>
          </div>

          {signUpMutation.error && (
            <AuthAlert>{extractErrorMessage(signUpMutation.error)}</AuthAlert>
          )}

          <div className="grid gap-4">
            <FormField
              control={form.control}
              name="full_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Full Name</FormLabel>
                  <FormControl>
                    <Input
                      data-testid="full-name-input"
                      placeholder="User"
                      type="text"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

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
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Password</FormLabel>
                  <FormControl>
                    <PasswordInput
                      data-testid="password-input"
                      placeholder="Password"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
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
                      placeholder="Confirm Password"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <LoadingButton
              type="submit"
              className="w-full"
              loading={signUpMutation.isPending}
            >
              Sign Up
            </LoadingButton>
          </div>

          <div className="text-center text-sm">
            Already have an account?{" "}
            <RouterLink to="/login" className="underline underline-offset-4">
              Log in
            </RouterLink>
          </div>
        </form>
      </Form>
    </AuthLayout>
  )
}

function CheckYourInbox({
  email,
  message,
}: {
  email: string
  message: string
}) {
  const resendVerification = useMutation({
    mutationFn: async () =>
      (await LoginService.resendVerification({ body: { email } })).data,
  })

  return (
    <div className="flex flex-col gap-6" data-testid="check-your-inbox">
      <div className="flex flex-col items-center gap-2 text-center">
        <MailCheck className="size-8 text-muted-foreground" />
        <h1 className="text-2xl font-bold">Check your inbox</h1>
        <p className="text-sm text-muted-foreground">{message}</p>
      </div>

      {resendVerification.data && (
        <AuthAlert tone="info">{resendVerification.data.message}</AuthAlert>
      )}
      {resendVerification.error && (
        <AuthAlert>{extractErrorMessage(resendVerification.error)}</AuthAlert>
      )}

      <div className="grid gap-4">
        <Button
          type="button"
          variant="outline"
          data-testid="resend-confirmation"
          disabled={resendVerification.isPending}
          onClick={() => resendVerification.mutate()}
        >
          Resend the confirmation link
        </Button>
      </div>

      <div className="text-center text-sm">
        Already confirmed?{" "}
        <RouterLink to="/login" className="underline underline-offset-4">
          Log in
        </RouterLink>
      </div>
    </div>
  )
}
