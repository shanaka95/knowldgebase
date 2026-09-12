import {
  Ban,
  CheckCircle2,
  CircleDashed,
  Clock,
  Cpu,
  History,
  type LucideIcon,
  Scissors,
  Sparkles,
  XCircle,
} from "lucide-react"

import type { EmbeddingState } from "@/lib/embeddingState"

export interface EmbeddingStateMeta {
  label: string
  description: string
  icon: LucideIcon
  spinner: boolean
  /** Tailwind classes for the badge surface. */
  badgeClass: string
  /** Tailwind classes for the small dot/icon variant. */
  iconClass: string
}

export const EMBEDDING_STATE_META: Record<EmbeddingState, EmbeddingStateMeta> =
  {
    none: {
      label: "Not indexed",
      description: "No embeddings have been generated for this page yet.",
      icon: CircleDashed,
      spinner: false,
      badgeClass: "border-border bg-muted/40 text-muted-foreground",
      iconClass: "text-muted-foreground",
    },
    pending: {
      label: "Queued",
      description: "Waiting for the indexing worker to pick this page up.",
      icon: Clock,
      spinner: false,
      badgeClass: "border-border bg-muted text-muted-foreground",
      iconClass: "text-muted-foreground",
    },
    chunking: {
      label: "Chunking",
      description: "The LLM is splitting the page into semantic sections.",
      icon: Scissors,
      spinner: true,
      badgeClass: "border-info/30 bg-info/10 text-info",
      iconClass: "text-info",
    },
    summarizing: {
      label: "Summarizing",
      description: "The LLM is writing a short summary of the page.",
      icon: Sparkles,
      spinner: true,
      badgeClass:
        "border-violet-500/30 bg-violet-500/10 text-violet-600 dark:text-violet-400",
      iconClass: "text-violet-600 dark:text-violet-400",
    },
    embedding: {
      label: "Embedding",
      description: "Generating vectors for the page, its summary and sections.",
      icon: Cpu,
      spinner: true,
      badgeClass: "border-primary/30 bg-primary/10 text-primary",
      iconClass: "text-primary",
    },
    ready: {
      label: "Indexed",
      description: "Embeddings are up to date with the latest version.",
      icon: CheckCircle2,
      spinner: false,
      badgeClass: "border-success/30 bg-success/10 text-success",
      iconClass: "text-success",
    },
    stale: {
      label: "Stale",
      description: "The page changed since it was last indexed.",
      icon: History,
      spinner: false,
      badgeClass:
        "border-warning/40 bg-warning/15 text-warning-foreground dark:text-warning",
      iconClass: "text-warning-foreground dark:text-warning",
    },
    failed: {
      label: "Failed",
      description: "Indexing failed. You can retry from the AI index panel.",
      icon: XCircle,
      spinner: false,
      badgeClass: "border-destructive/30 bg-destructive/10 text-destructive",
      iconClass: "text-destructive",
    },
  }

export const CANCELLED_ICON = Ban
