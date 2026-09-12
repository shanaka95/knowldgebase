import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"

export const APP_NAME = "PlusGPT"
export const APP_TAGLINE = "a personal knowledge management system"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

/**
 * The mark, drawn rather than loaded, so it inherits crisp rendering at every
 * size and needs no network request. It matches `public/favicon.svg` exactly.
 */
function Mark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex size-7 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-indigo-500 to-violet-500 text-white",
        className,
      )}
      aria-hidden="true"
    >
      {/* The wrapper is aria-hidden and the name sits beside it, so this
          title exists for tooling rather than to be announced twice. */}
      <svg
        viewBox="0 0 64 64"
        className="size-4"
        fill="none"
        stroke="currentColor"
        strokeWidth={8}
        strokeLinecap="round"
      >
        <title>PlusGPT</title>
        <path d="M32 15.2v33.6M15.2 32h33.6" />
      </svg>
    </span>
  )
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content =
    variant === "responsive" ? (
      <span className={cn("flex items-center gap-2", className)}>
        <Mark />
        <span className="font-semibold text-sm tracking-tight group-data-[collapsible=icon]:hidden">
          {APP_NAME}
        </span>
      </span>
    ) : variant === "icon" ? (
      <Mark className={className} />
    ) : (
      <span className={cn("flex items-center gap-2.5", className)}>
        <Mark className="size-9 rounded-lg [&>svg]:size-5" />
        <span className="font-semibold text-lg tracking-tight">{APP_NAME}</span>
      </span>
    )

  if (!asLink) {
    return content
  }

  return (
    <Link to="/" className="inline-flex items-center">
      {content}
    </Link>
  )
}
