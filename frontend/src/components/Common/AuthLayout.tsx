import { Link as RouterLink } from "@tanstack/react-router"
import type { ReactNode } from "react"

import { Appearance } from "@/components/Common/Appearance"
import { APP_NAME, APP_TAGLINE, Logo } from "@/components/Common/Logo"

/**
 * The shell every signed-out page shares.
 *
 * Two columns on a wide screen: what this is on the left, what to do about it
 * on the right. The left half is decoration on a phone and is dropped there —
 * a person on a 390px screen wants the field, not the pitch.
 *
 * `hero` lets one page say more than the others. Sign-in uses it, because for
 * now that page is also the landing page; the rest keep the short version,
 * since somebody resetting a password has already decided.
 */

interface AuthLayoutProps {
  children: ReactNode
  hero?: ReactNode
  /** The same pitch in two lines, shown above the form where `hero` is not. */
  heroCompact?: ReactNode
}

export function AuthLayout({ children, hero, heroCompact }: AuthLayoutProps) {
  return (
    <div className="grid min-h-svh grid-cols-1 lg:grid-cols-[1.05fr_1fr]">
      <div className="relative hidden overflow-hidden bg-muted lg:flex lg:flex-col lg:justify-between lg:p-12 dark:bg-sidebar">
        {/* Two washes rather than one: a single radial reads as a smudge in a
            corner, while a second, dimmer one at the opposite edge gives the
            panel a direction without anybody noticing why. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_left,color-mix(in_oklch,var(--primary)_18%,transparent),transparent_60%)]"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_bottom_right,color-mix(in_oklch,var(--primary)_10%,transparent),transparent_55%)]"
        />
        <Logo variant="full" asLink={false} />
        <div className="relative">
          {hero ?? (
            <div className="max-w-md space-y-3">
              <h2 className="font-semibold text-3xl tracking-tight">
                {APP_NAME} — {APP_TAGLINE}.
              </h2>
              <p className="text-muted-foreground">
                Spaces, folders and beautifully written pages — searchable,
                shareable, and indexed for AI.
              </p>
            </div>
          )}
        </div>
        <div className="relative flex items-center gap-4 text-muted-foreground text-xs">
          <span>
            {APP_NAME} · {new Date().getFullYear()}
          </span>
          <LegalLinks className="ml-auto" />
        </div>
      </div>

      <div className="flex flex-col gap-4 p-6 md:p-10">
        <div className="flex items-center justify-between lg:justify-end">
          <span className="lg:hidden">
            <Logo variant="responsive" asLink={false} />
          </span>
          <Appearance />
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="flex w-full max-w-sm flex-col gap-8">
            {heroCompact && <div className="lg:hidden">{heroCompact}</div>}
            {children}
          </div>
        </div>
        {/* Reachable from every signed-out page, and on a phone this is the
            only place they appear. */}
        <LegalLinks className="justify-center text-xs lg:hidden" />
      </div>
    </div>
  )
}

export function LegalLinks({ className }: { className?: string }) {
  return (
    <span
      className={`flex items-center gap-4 text-muted-foreground ${className ?? ""}`}
    >
      <RouterLink to="/privacy" className="transition hover:text-foreground">
        Privacy
      </RouterLink>
      <RouterLink to="/terms" className="transition hover:text-foreground">
        Terms
      </RouterLink>
    </span>
  )
}
