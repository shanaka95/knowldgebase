import { Link as RouterLink } from "@tanstack/react-router"
import { ArrowLeft } from "lucide-react"
import type { ReactNode } from "react"

import { Appearance } from "@/components/Common/Appearance"
import { APP_NAME, Logo } from "@/components/Common/Logo"

/**
 * The shell the policy pages share.
 *
 * Public, and deliberately plain: somebody reading a privacy policy wants to
 * read it, not be marketed to. One column, generous measure, and a way back to
 * where they came from.
 */

export const LEGAL_UPDATED = "15 September 2026"

export function LegalPage({
  title,
  intro,
  children,
}: {
  title: string
  intro: ReactNode
  children: ReactNode
}) {
  return (
    <div className="flex min-h-svh flex-col bg-background">
      <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
        <div className="mx-auto flex w-full max-w-3xl items-center justify-between gap-4 px-6 py-3">
          <Logo variant="responsive" asLink={false} />
          <div className="flex items-center gap-1">
            <Appearance />
            <RouterLink
              to="/login"
              className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-muted-foreground text-sm transition hover:text-foreground"
            >
              <ArrowLeft className="size-4" />
              Back
            </RouterLink>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-12">
        <p className="font-medium text-muted-foreground text-sm">
          Last updated {LEGAL_UPDATED}
        </p>
        <h1 className="mt-2 font-semibold text-3xl tracking-tight sm:text-4xl">
          {title}
        </h1>
        <div className="mt-4 text-lg text-muted-foreground leading-relaxed">
          {intro}
        </div>
        <div className="mt-10 flex flex-col gap-10">{children}</div>
      </main>

      <footer className="border-t">
        <div className="mx-auto flex w-full max-w-3xl flex-wrap items-center gap-x-4 gap-y-2 px-6 py-6 text-muted-foreground text-sm">
          <span>
            {APP_NAME} · {new Date().getFullYear()}
          </span>
          <span className="ml-auto flex gap-4">
            <RouterLink
              to="/privacy"
              className="transition hover:text-foreground"
            >
              Privacy
            </RouterLink>
            <RouterLink
              to="/terms"
              className="transition hover:text-foreground"
            >
              Terms
            </RouterLink>
          </span>
        </div>
      </footer>
    </div>
  )
}

export function Section({
  id,
  title,
  children,
}: {
  id: string
  title: string
  children: ReactNode
}) {
  return (
    <section id={id} className="scroll-mt-20">
      <h2 className="font-semibold text-xl tracking-tight">{title}</h2>
      <div className="mt-3 flex flex-col gap-3 text-[0.95rem] leading-relaxed [&_a]:underline [&_a]:underline-offset-4 [&_li]:leading-relaxed [&_strong]:font-medium">
        {children}
      </div>
    </section>
  )
}

export function Bullets({ items }: { items: ReactNode[] }) {
  return (
    <ul className="flex list-disc flex-col gap-2 pl-5">
      {items.map((item, i) => (
        // Static prose, written in place and never reordered, so the position
        // is the identity.
        <li key={`item-${i}`}>{item}</li>
      ))}
    </ul>
  )
}

/**
 * Something the operator of this installation has to fill in.
 *
 * Marked rather than guessed: a policy that states the wrong legal entity or
 * the wrong jurisdiction is worse than one that visibly has a blank in it.
 */
export function Placeholder({ children }: { children: ReactNode }) {
  return (
    <span className="rounded bg-warning/15 px-1.5 py-0.5 font-medium text-foreground ring-1 ring-warning/40 ring-inset">
      {children}
    </span>
  )
}
