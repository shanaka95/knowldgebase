import { format, formatDistanceToNowStrict } from "date-fns"
import { Check, Pencil } from "lucide-react"

import type { DocumentPublic } from "@/client"
import { EmbeddingStatusPill } from "@/components/Embeddings/EmbeddingStatusPill"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { Kbd } from "@/components/ui/kbd"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { UseAutosaveResult } from "@/hooks/useAutosave"
import type { EmbeddingState } from "@/lib/embeddingState"
import { getInitials } from "@/utils"
import { DocumentMenu } from "./DocumentMenu"
import { DocumentTitle } from "./DocumentTitle"
import { SaveIndicator } from "./SaveIndicator"

interface DocumentHeaderProps {
  document: DocumentPublic
  namespaceSlug: string
  title: string
  onTitleChange: (value: string) => void
  onTitleSubmit: () => void
  mode: "view" | "edit"
  canEdit: boolean
  onEdit: () => void
  onDone: () => void
  finishing: boolean
  autosave: UseAutosaveResult
  embedding: {
    state: EmbeddingState
    progress: number | null
    chunkCount?: number | null
    chunkingMethod?: string | null
    updatedAt?: string | null
    error?: string | null
    attempts?: number | null
    maxAttempts?: number | null
  }
  aiPanelOpen: boolean
  onToggleAiPanel: () => void
  extra?: React.ReactNode
}

export function DocumentHeader({
  document,
  namespaceSlug,
  title,
  onTitleChange,
  onTitleSubmit,
  mode,
  canEdit,
  onEdit,
  onDone,
  finishing,
  autosave,
  embedding,
  aiPanelOpen,
  onToggleAiPanel,
  extra,
}: DocumentHeaderProps) {
  const updatedBy =
    document.updated_by_user?.full_name ||
    document.updated_by_user?.email ||
    null
  const updatedAt = document.updated_at ? new Date(document.updated_at) : null

  return (
    <header className="flex flex-col gap-4" data-testid="document-header">
      <div className="flex flex-wrap items-center gap-2">
        <EmbeddingStatusPill
          state={embedding.state}
          progress={embedding.progress}
          chunkCount={embedding.chunkCount}
          chunkingMethod={embedding.chunkingMethod}
          updatedAt={embedding.updatedAt}
          detail={embedding.error ?? undefined}
          attempts={embedding.attempts}
          maxAttempts={embedding.maxAttempts}
          onClick={onToggleAiPanel}
        />
        {extra}
        <div className="ml-auto flex items-center gap-2">
          {mode === "edit" && (
            <SaveIndicator
              status={autosave.status}
              lastSavedAt={autosave.lastSavedAt}
              error={autosave.error}
              onRetry={() => void autosave.retry()}
            />
          )}
          {canEdit &&
            (mode === "view" ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button size="sm" onClick={onEdit} data-testid="edit-button">
                    <Pencil className="size-3.5" />
                    Edit
                  </Button>
                </TooltipTrigger>
                <TooltipContent
                  side="bottom"
                  className="flex items-center gap-1.5"
                >
                  Edit page <Kbd>E</Kbd>
                </TooltipContent>
              </Tooltip>
            ) : (
              <LoadingButton
                size="sm"
                onClick={onDone}
                loading={finishing}
                data-testid="done-button"
              >
                <Check className="size-3.5" />
                Done
              </LoadingButton>
            ))}
          <DocumentMenu
            document={document}
            namespaceSlug={namespaceSlug}
            canEdit={canEdit}
            aiPanelOpen={aiPanelOpen}
            onToggleAiPanel={onToggleAiPanel}
          />
        </div>
      </div>

      <DocumentTitle
        value={title}
        editable={mode === "edit"}
        onChange={onTitleChange}
        onSubmit={onTitleSubmit}
      />

      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {updatedBy && (
          <Avatar className="size-5">
            <AvatarFallback className="text-[9px]">
              {getInitials(updatedBy)}
            </AvatarFallback>
          </Avatar>
        )}
        <Tooltip>
          <TooltipTrigger asChild>
            <span data-testid="document-meta">
              {updatedBy ? `Updated by ${updatedBy}` : "Updated"}
              {updatedAt && ` · ${formatDistanceToNowStrict(updatedAt)} ago`}
              {` · v${document.version}`}
            </span>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="text-xs">
            {updatedAt && <div>Updated {format(updatedAt, "PPpp")}</div>}
            {document.created_at && (
              <div>
                Created {format(new Date(document.created_at), "PPpp")}
                {document.created_by_user &&
                  ` by ${document.created_by_user.full_name || document.created_by_user.email}`}
              </div>
            )}
          </TooltipContent>
        </Tooltip>
      </div>
    </header>
  )
}

export default DocumentHeader
