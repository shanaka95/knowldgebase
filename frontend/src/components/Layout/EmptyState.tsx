import type { LucideIcon } from "lucide-react"

import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { cn } from "@/lib/utils"

interface EmptyStateProps {
  icon?: LucideIcon
  title: React.ReactNode
  description?: React.ReactNode
  action?: React.ReactNode
  className?: string
  compact?: boolean
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
  compact = false,
}: EmptyStateProps) {
  return (
    <Empty
      className={cn(
        compact ? "py-8" : "py-16",
        "border border-dashed",
        className,
      )}
    >
      <EmptyHeader>
        {Icon && (
          <EmptyMedia variant="icon">
            <Icon />
          </EmptyMedia>
        )}
        {/*
          A title can carry text somebody typed - "No results for …" - and one
          long unbroken word in a search box pushed the whole page sideways on
          a phone. Breaking inside the word is the only thing that can give.
        */}
        <EmptyTitle className="max-w-full break-words">{title}</EmptyTitle>
        {description && (
          <EmptyDescription className="max-w-full break-words">
            {description}
          </EmptyDescription>
        )}
      </EmptyHeader>
      {action && <EmptyContent>{action}</EmptyContent>}
    </Empty>
  )
}
