import { Appearance } from "@/components/Common/Appearance"
import { APP_NAME, APP_TAGLINE, Logo } from "@/components/Common/Logo"

interface AuthLayoutProps {
  children: React.ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="grid grid-cols-1 min-h-svh lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-muted lg:flex lg:flex-col lg:justify-between lg:p-12 dark:bg-sidebar">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_left,color-mix(in_oklch,var(--primary)_18%,transparent),transparent_60%)]"
        />
        <Logo variant="full" asLink={false} />
        <div className="relative max-w-md space-y-3">
          <h2 className="text-3xl font-semibold tracking-tight">
            {APP_NAME} — {APP_TAGLINE}.
          </h2>
          <p className="text-muted-foreground">
            Spaces, folders and beautifully written pages — searchable,
            shareable, and indexed for AI with local models.
          </p>
        </div>
        <p className="relative text-xs text-muted-foreground">
          {APP_NAME} · {new Date().getFullYear()}
        </p>
      </div>
      <div className="flex flex-col gap-4 p-6 md:p-10">
        <div className="flex items-center justify-between lg:justify-end">
          <span className="lg:hidden">
            <Logo variant="responsive" asLink={false} />
          </span>
          <Appearance />
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-xs">{children}</div>
        </div>
      </div>
    </div>
  )
}
