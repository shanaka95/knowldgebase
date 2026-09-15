import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import {
  createFileRoute,
  Link as RouterLink,
  redirect,
} from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import {
  type Body_login_login_access_token as AccessToken,
  type LoginChallenge,
  LoginService,
} from "@/client"
import { AuthAlert } from "@/components/Common/AuthAlert"
import { AuthLayout } from "@/components/Common/AuthLayout"
import {
  LandingHero,
  LandingHeroCompact,
} from "@/components/Common/LandingHero"
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
import { errorStatus, extractErrorMessage } from "@/utils"

/** Long enough to outlast a slow delivery, short enough not to feel punitive. */
const RESEND_COOLDOWN_SECONDS = 30

const formSchema = z.object({
  username: z.email({ message: "Invalid email address" }),
  password: z
    .string()
    .min(1, { message: "Password is required" })
    .min(8, { message: "Password must be at least 8 characters" }),
}) satisfies z.ZodType<AccessToken>

type FormData = z.infer<typeof formSchema>

type Auth = ReturnType<typeof useAuth>

export const Route = createFileRoute("/login")({
  component: Login,
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
        title: "Log In - PlusGPT",
      },
    ],
  }),
})

function Login() {
  const {
    loginMutation,
    verifyCodeMutation,
    resendCodeMutation,
    challenge,
    clearChallenge,
  } = useAuth()

  return (
    <AuthLayout hero={<LandingHero />} heroCompact={<LandingHeroCompact />}>
      {challenge ? (
        <CodePane
          challenge={challenge}
          verifyCodeMutation={verifyCodeMutation}
          resendCodeMutation={resendCodeMutation}
          onBack={clearChallenge}
        />
      ) : (
        <PasswordPane loginMutation={loginMutation} />
      )}
    </AuthLayout>
  )
}

function PasswordPane({
  loginMutation,
}: {
  loginMutation: Auth["loginMutation"]
}) {
  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      username: "",
      password: "",
    },
  })

  const resendVerification = useMutation({
    mutationFn: async (email: string) =>
      (await LoginService.resendVerification({ body: { email } })).data,
  })

  const onSubmit = (data: FormData) => {
    if (loginMutation.isPending) return
    resendVerification.reset()
    loginMutation.mutate(data)
  }

  // 403 is the one sign-in failure with something useful to offer: the address
  // exists but has never been confirmed, so send the link again.
  const needsConfirmation = errorStatus(loginMutation.error) === 403

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(onSubmit)}
        className="flex flex-col gap-6"
      >
        <div className="flex flex-col gap-1.5">
          <h1 className="font-semibold text-2xl tracking-tight">
            Welcome back
          </h1>
          <p className="text-muted-foreground text-sm">
            Sign in to your knowledge base.
          </p>
        </div>

        {loginMutation.error && (
          <AuthAlert>{extractErrorMessage(loginMutation.error)}</AuthAlert>
        )}

        {needsConfirmation && (
          <div className="flex flex-col gap-2">
            <Button
              type="button"
              variant="outline"
              data-testid="resend-confirmation"
              disabled={resendVerification.isPending}
              onClick={() =>
                resendVerification.mutate(form.getValues("username"))
              }
            >
              Resend the confirmation link
            </Button>
            {resendVerification.data && (
              <AuthAlert tone="info">
                {resendVerification.data.message}
              </AuthAlert>
            )}
            {resendVerification.error && (
              <AuthAlert>
                {extractErrorMessage(resendVerification.error)}
              </AuthAlert>
            )}
          </div>
        )}

        <div className="grid gap-4">
          <FormField
            control={form.control}
            name="username"
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

          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <div className="flex items-center justify-between">
                  <FormLabel>Password</FormLabel>
                  <RouterLink
                    to="/forgot-password"
                    className="text-xs text-muted-foreground underline underline-offset-4"
                  >
                    Forgot your password?
                  </RouterLink>
                </div>
                <FormControl>
                  <PasswordInput
                    data-testid="password-input"
                    placeholder="Password"
                    autoComplete="current-password"
                    {...field}
                  />
                </FormControl>
                <FormMessage className="text-xs" />
              </FormItem>
            )}
          />

          <LoadingButton type="submit" loading={loginMutation.isPending}>
            Log In
          </LoadingButton>
        </div>

        <div className="flex flex-col gap-3 text-center text-sm">
          <span>
            Don't have an account yet?{" "}
            <RouterLink to="/signup" className="underline underline-offset-4">
              Sign up
            </RouterLink>
          </span>
          {/* Said where the decision is made rather than only in a footer. */}
          <span className="text-muted-foreground text-xs leading-relaxed">
            By continuing you agree to the{" "}
            <RouterLink to="/terms" className="underline underline-offset-4">
              Terms
            </RouterLink>{" "}
            and the{" "}
            <RouterLink to="/privacy" className="underline underline-offset-4">
              Privacy Policy
            </RouterLink>
            .
          </span>
        </div>
      </form>
    </Form>
  )
}

function CodePane({
  challenge,
  verifyCodeMutation,
  resendCodeMutation,
  onBack,
}: {
  challenge: LoginChallenge
  verifyCodeMutation: Auth["verifyCodeMutation"]
  resendCodeMutation: Auth["resendCodeMutation"]
  onBack: () => void
}) {
  const [code, setCode] = useState("")
  const [cooldown, setCooldown] = useState(RESEND_COOLDOWN_SECONDS)

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = setTimeout(() => setCooldown((seconds) => seconds - 1), 1000)
    return () => clearTimeout(timer)
  }, [cooldown])

  const submit = (value: string) => {
    if (value.length !== challenge.code_length) return
    if (verifyCodeMutation.isPending) return
    verifyCodeMutation.mutate(value)
  }

  const onChange = (value: string) => {
    // Codes are digits only, so anything else is a stray keystroke or a paste
    // of the surrounding text; dropping it keeps auto-submit predictable.
    const digits = value.replace(/\D/g, "").slice(0, challenge.code_length)
    setCode(digits)
    submit(digits)
  }

  const error = verifyCodeMutation.error ?? resendCodeMutation.error

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        submit(code)
      }}
      className="flex flex-col gap-6"
    >
      <div className="flex flex-col items-center gap-2 text-center">
        <h1 className="text-2xl font-bold">Enter your code</h1>
        <p className="text-sm text-muted-foreground">
          We sent a code to{" "}
          <span className="font-medium text-foreground">
            {challenge.sent_to}
          </span>
        </p>
      </div>

      {!challenge.delivered && (
        <AuthAlert>
          We could not email the code just now. Try sending another one shortly.
        </AuthAlert>
      )}

      {error && <AuthAlert>{extractErrorMessage(error)}</AuthAlert>}

      <div className="grid gap-4">
        <div className="grid gap-2">
          <label htmlFor="code" className="text-sm font-medium">
            {challenge.code_length}-digit code
          </label>
          <Input
            id="code"
            data-testid="code-input"
            value={code}
            onChange={(event) => onChange(event.target.value)}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={challenge.code_length}
            placeholder={"0".repeat(challenge.code_length)}
            autoFocus
            className="text-center text-lg tracking-[0.4em] font-mono"
          />
        </div>

        <LoadingButton
          type="submit"
          loading={verifyCodeMutation.isPending}
          disabled={code.length !== challenge.code_length}
        >
          Continue
        </LoadingButton>

        <Button
          type="button"
          variant="outline"
          data-testid="resend-code"
          disabled={cooldown > 0 || resendCodeMutation.isPending}
          onClick={() =>
            resendCodeMutation.mutate(undefined, {
              onSuccess: () => {
                setCode("")
                setCooldown(RESEND_COOLDOWN_SECONDS)
              },
            })
          }
        >
          {cooldown > 0
            ? `Send another code (${cooldown}s)`
            : "Send another code"}
        </Button>
      </div>

      <div className="text-center text-sm">
        <button
          type="button"
          onClick={onBack}
          data-testid="back-to-password"
          className="underline underline-offset-4"
        >
          Back
        </button>
      </div>
    </form>
  )
}
