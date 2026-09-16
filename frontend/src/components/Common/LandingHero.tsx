import type { LucideIcon } from "lucide-react"
import { FileSearch, MessagesSquare, ShieldCheck, Sparkles } from "lucide-react"

import { APP_NAME } from "@/components/Common/Logo"

/**
 * The half of the sign-in page that is a landing page.
 *
 * Minimal on purpose: somebody arriving here is one field away from being
 * useful to, so the job is to say what this is in a breath and get out of the
 * way. Four claims, each one a thing the product actually does — no
 * testimonials, no logos, nothing that has to be maintained as a fiction.
 */

const POINTS: { icon: LucideIcon; title: string; body: string }[] = [
  {
    icon: MessagesSquare,
    title: "Answers you can check",
    body: "Every answer shows the passages it came from, so you can see where it got that.",
  },
  {
    icon: FileSearch,
    title: "Search by wording or meaning",
    body: "Keyword and meaning search run together, so a page turns up even when you forget the exact words.",
  },
  {
    icon: Sparkles,
    title: "Drop in a PDF, get a page",
    body: "Scans are transcribed, organised and indexed. The original stays one click away.",
  },
  {
    icon: ShieldCheck,
    title: "Private until you share it",
    body: "Share a space, a folder or a single page. Turn a link off and it stays off.",
  },
]

/**
 * The same claim in one breath, for a phone.
 *
 * The full panel is dropped below `lg`, and a landing page that says nothing
 * about itself on the device most people arrive on is not a landing page. Two
 * lines, above the form, and then out of the way.
 */
export function LandingHeroCompact() {
  return (
    <div className="flex flex-col gap-1.5 text-balance">
      <h2 className="font-semibold text-2xl leading-tight tracking-tight">
        Everything you know,{" "}
        <span className="text-primary">one question away.</span>
      </h2>
      <p className="text-muted-foreground text-sm leading-relaxed">
        {APP_NAME} turns the documents you already have into something you can
        actually ask.
      </p>
    </div>
  )
}

export function LandingHero() {
  return (
    <div className="relative flex flex-col gap-8">
      <div className="space-y-4">
        <h2 className="text-balance font-semibold text-4xl leading-[1.1] tracking-tight xl:text-5xl">
          Everything you know,
          <br />
          <span className="text-primary">one question away.</span>
        </h2>
        <p className="max-w-md text-balance text-lg text-muted-foreground leading-relaxed">
          {APP_NAME} turns the documents you already have into something you can
          actually ask.
        </p>
      </div>

      <ul className="flex max-w-md flex-col gap-4">
        {POINTS.map(({ icon: Icon, title, body }) => (
          <li key={title} className="flex items-start gap-3">
            <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary ring-1 ring-primary/15 ring-inset">
              <Icon className="size-4" />
            </span>
            <span className="min-w-0">
              <span className="block font-medium text-sm">{title}</span>
              <span className="mt-0.5 block text-muted-foreground text-sm leading-relaxed">
                {body}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
