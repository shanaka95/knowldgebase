import {
  BrainCircuit,
  Copy,
  FolderInput,
  Link2,
  MoreHorizontal,
  Pencil,
  Share2,
  Trash2,
} from "lucide-react"
import { toast } from "sonner"

import type { DocumentPublic } from "@/client"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import { openDialog } from "@/stores/dialogs"

interface DocumentMenuProps {
  document: DocumentPublic
  namespaceSlug: string
  canEdit: boolean
  aiPanelOpen: boolean
  onToggleAiPanel: () => void
}

export function DocumentMenu({
  document,
  namespaceSlug,
  canEdit,
  aiPanelOpen,
  onToggleAiPanel,
}: DocumentMenuProps) {
  const [, copy] = useCopyToClipboard()
  const target = {
    type: "document" as const,
    id: document.id,
    namespaceId: document.namespace_id,
    namespaceSlug,
    title: document.title,
    folderId: document.folder_id ?? null,
  }

  const copyLink = async () => {
    const url = `${window.location.origin}/s/${namespaceSlug}/d/${document.id}`
    const ok = await copy(url)
    if (ok) toast.success("Link copied")
    else toast.error("Couldn't copy the link")
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="More actions"
          data-testid="document-menu"
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        {canEdit && (
          <>
            <DropdownMenuItem
              onSelect={() => openDialog({ kind: "share", target })}
            >
              <Share2 />
              Share
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => openDialog({ kind: "move", target })}
            >
              <FolderInput />
              Move to…
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => openDialog({ kind: "rename", target })}
            >
              <Pencil />
              Rename
            </DropdownMenuItem>
            <DropdownMenuSeparator />
          </>
        )}
        <DropdownMenuItem onSelect={() => void copyLink()}>
          <Link2 />
          Copy link
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => openDialog({ kind: "copy", target })}
          data-testid="document-make-a-copy"
        >
          <Copy />
          Make a copy
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={onToggleAiPanel}>
          <BrainCircuit />
          {aiPanelOpen ? "Hide AI index" : "Show AI index"}
          <DropdownMenuShortcut>⌥I</DropdownMenuShortcut>
        </DropdownMenuItem>
        {canEdit && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant="destructive"
              onSelect={() => openDialog({ kind: "delete", target })}
            >
              <Trash2 />
              Delete
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export default DocumentMenu
