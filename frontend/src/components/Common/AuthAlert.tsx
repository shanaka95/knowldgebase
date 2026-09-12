import { CircleAlert, Info } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"

interface AuthAlertProps {
  tone?: "error" | "info"
  children: React.ReactNode
}

/**
 * The one place the auth pages say something back to the user. Messages from
 * the API are shown verbatim — the backend words them carefully so that a
 * stranger cannot learn from them whether an address has an account.
 */
export function AuthAlert({ tone = "error", children }: AuthAlertProps) {
  const isError = tone === "error"
  return (
    <Alert
      variant={isError ? "destructive" : "default"}
      data-testid={isError ? "auth-error" : "auth-info"}
    >
      {isError ? <CircleAlert /> : <Info />}
      <AlertDescription className={isError ? "text-destructive/90" : undefined}>
        {children}
      </AlertDescription>
    </Alert>
  )
}
