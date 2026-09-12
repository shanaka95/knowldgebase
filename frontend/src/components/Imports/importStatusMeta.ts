import {
  Ban,
  CheckCircle2,
  Clock,
  FileCog,
  type LucideIcon,
  ScanText,
  Sparkles,
  XCircle,
} from "lucide-react"

import type { ImportStatus } from "@/client"

export interface ImportStatusMeta {
  label: string
  description: string
  icon: LucideIcon
  spinner: boolean
  badgeClass: string
}

export const IMPORT_STATUS_META: Record<ImportStatus, ImportStatusMeta> = {
  queued: {
    label: "Queued",
    description: "Waiting for the import worker to pick this file up.",
    icon: Clock,
    spinner: false,
    badgeClass: "border-border bg-muted text-muted-foreground",
  },
  rendering: {
    label: "Rendering",
    description: "Fetching the file and turning its pages into images.",
    icon: FileCog,
    spinner: true,
    badgeClass: "border-info/30 bg-info/10 text-info",
  },
  parsing: {
    label: "Parsing",
    description:
      "A vision model is reading each page and extracting headings, text and tables.",
    icon: ScanText,
    spinner: true,
    badgeClass:
      "border-indigo-500/30 bg-indigo-500/10 text-indigo-600 dark:text-indigo-400",
  },
  creating: {
    label: "Creating page",
    description: "Writing the page and attaching the original file.",
    icon: Sparkles,
    spinner: true,
    badgeClass:
      "border-violet-500/30 bg-violet-500/10 text-violet-600 dark:text-violet-400",
  },
  done: {
    label: "Imported",
    description: "The page was created and is being indexed like any other.",
    icon: CheckCircle2,
    spinner: false,
    badgeClass: "border-success/30 bg-success/10 text-success",
  },
  failed: {
    label: "Failed",
    description: "The file could not be turned into a page.",
    icon: XCircle,
    spinner: false,
    badgeClass: "border-destructive/30 bg-destructive/10 text-destructive",
  },
  cancelled: {
    label: "Cancelled",
    description: "The import was stopped before it finished.",
    icon: Ban,
    spinner: false,
    badgeClass: "border-border bg-muted text-muted-foreground",
  },
}

export const PARSER_LABELS: Record<string, string> = {
  mineru: "MinerU",
  llm: "LLM fallback",
}

export const PARSER_DESCRIPTIONS: Record<string, string> = {
  mineru:
    "Parsed by MinerU2.5, a document model that detects layout and keeps tables intact.",
  llm: "MinerU was unreachable, so the general multimodal model transcribed the pages. Tables and layout are less reliable.",
}
