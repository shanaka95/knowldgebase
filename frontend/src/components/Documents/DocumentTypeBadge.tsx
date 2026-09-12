import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

interface DocumentTypeBadgeProps {
  type?: string | null
  className?: string
}

/**
 * The page's type, wherever pages are shown. Renders nothing when a page has no
 * type, so untyped pages look exactly as they did before.
 */
export function DocumentTypeBadge({ type, className }: DocumentTypeBadgeProps) {
  const label = type?.trim()
  if (!label) return null
  return (
    <Badge
      variant="secondary"
      className={cn(
        "max-w-[12rem] shrink-0 truncate px-1.5 py-0 text-[10px] font-normal text-muted-foreground",
        className,
      )}
      title={label}
      data-testid="document-type-badge"
    >
      {label}
    </Badge>
  )
}

export default DocumentTypeBadge
