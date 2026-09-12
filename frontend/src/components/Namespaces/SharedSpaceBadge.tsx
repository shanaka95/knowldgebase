import { Users } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

const EXPLANATION =
  "Shared with you. This space belongs to someone else — its owner decides who is in it and can withdraw your access."

/**
 * The mark that a space is not yours, shown wherever a space is named.
 *
 * Driven by the backend's `shared_with_you` rather than by comparing owner ids:
 * a superuser sees spaces they do not belong to, and an id comparison would
 * quietly call those "mine".
 */
export function SharedSpaceBadge({
  shared,
  withLabel = false,
  className,
}: {
  shared?: boolean
  /** Off where space is tight: the icon carries the meaning, the tooltip the words. */
  withLabel?: boolean
  className?: string
}) {
  if (!shared) return null
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge
          variant="outline"
          className={cn(
            "gap-1 px-1.5 py-0 text-[10px] font-normal tracking-wide uppercase",
            className,
          )}
          data-testid="shared-space-badge"
        >
          <Users aria-hidden="true" />
          {/* The words are always in the accessibility tree, label or no label:
              a tooltip on hover is not readable by anyone who never hovers. */}
          <span className={withLabel ? undefined : "sr-only"}>
            Shared with you
          </span>
        </Badge>
      </TooltipTrigger>
      <TooltipContent>{EXPLANATION}</TooltipContent>
    </Tooltip>
  )
}
