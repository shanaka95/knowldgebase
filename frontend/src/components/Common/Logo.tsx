import { Link } from "@tanstack/react-router"
import { BookOpenText } from "lucide-react"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

function Mark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex size-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground",
        className,
      )}
    >
      <BookOpenText className="size-4" />
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
        <span className="text-sm font-semibold tracking-tight group-data-[collapsible=icon]:hidden">
          Knowledge Base
        </span>
      </span>
    ) : variant === "icon" ? (
      <Mark className={className} />
    ) : (
      <span className={cn("flex items-center gap-2.5", className)}>
        <Mark className="size-9 rounded-lg [&>svg]:size-5" />
        <span className="text-lg font-semibold tracking-tight">
          Knowledge Base
        </span>
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
