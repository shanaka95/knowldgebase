import { Loader2 } from "lucide-react"

import type { ImportJobPublic } from "@/client"
import { Badge } from "@/components/ui/badge"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { IMPORT_STATUS_META } from "./importStatusMeta"

interface Props {
  job: ImportJobPublic
  className?: string
}

export function ImportStatusPill({ job, className }: Props) {
  const meta = IMPORT_STATUS_META[job.status]
  const Icon = meta.icon
  const pagesTotal = job.pages_total ?? 0
  const pagesDone = job.pages_done ?? 0
  const showPages = job.status === "parsing" && pagesTotal > 0

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge
          variant="outline"
          className={cn(
            "h-6 gap-1.5 rounded-full px-2.5 text-xs font-medium",
            meta.badgeClass,
            className,
          )}
          data-testid="import-status-pill"
          data-status={job.status}
        >
          {meta.spinner ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Icon className="size-3.5" />
          )}
          <span>{meta.label}</span>
          {showPages && (
            <span className="tabular-nums opacity-80">
              {pagesDone}/{pagesTotal}
            </span>
          )}
        </Badge>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-xs">
        <p className="font-medium">{meta.label}</p>
        <p className="text-xs opacity-80">{job.error ?? meta.description}</p>
      </TooltipContent>
    </Tooltip>
  )
}

export default ImportStatusPill
