import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { ChevronRight, Folder, FolderOpen, Home } from "lucide-react"
import { useMemo, useState } from "react"

import type { FolderPublic } from "@/client"
import { NamespaceIcon } from "@/components/Namespaces/NamespaceIcon"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useMoveNode } from "@/hooks/useKbMutations"
import { canEditNamespace, useNamespaces } from "@/hooks/useNamespaces"
import { cn } from "@/lib/utils"
import { type TreeIndex, treeQuery } from "@/queries/namespaces"
import type { DialogTarget } from "@/stores/dialogs"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  target: Extract<DialogTarget, { type: "folder" | "document" }>
}

function FolderOption({
  folder,
  index,
  depth,
  selected,
  disabled,
  onSelect,
}: {
  folder: FolderPublic
  index: TreeIndex
  depth: number
  selected: string | null
  disabled: Set<string>
  onSelect: (id: string) => void
}) {
  const [open, setOpen] = useState(depth < 1)
  const children = index.childrenOf(folder.id)
  const isDisabled = disabled.has(folder.id)
  const isSelected = selected === folder.id
  return (
    <li>
      <div
        className={cn(
          "flex h-8 items-center gap-1 rounded-md pr-2 text-sm",
          isSelected && "bg-primary/10 text-primary",
          !isSelected && !isDisabled && "hover:bg-accent",
          isDisabled && "opacity-40",
        )}
        style={{ paddingLeft: `${depth * 16 + 4}px` }}
        data-testid="move-folder-option"
      >
        <button
          type="button"
          aria-label={open ? "Collapse" : "Expand"}
          className={cn(
            "flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground",
            children.length === 0 && "invisible",
          )}
          onClick={() => setOpen((v) => !v)}
        >
          <ChevronRight
            className={cn("size-3.5 transition-transform", open && "rotate-90")}
          />
        </button>
        <button
          type="button"
          aria-pressed={isSelected}
          disabled={isDisabled}
          onClick={() => onSelect(folder.id)}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left disabled:cursor-not-allowed"
        >
          {open ? (
            <FolderOpen className="size-4 shrink-0 text-muted-foreground" />
          ) : (
            <Folder className="size-4 shrink-0 text-muted-foreground" />
          )}
          <span className="truncate">{folder.name}</span>
        </button>
      </div>
      {open && children.length > 0 && (
        <ul>
          {children.map((child) => (
            <FolderOption
              key={child.id}
              folder={child}
              index={index}
              depth={depth + 1}
              selected={selected}
              disabled={disabled}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

export function MoveDialog({ open, onOpenChange, target }: Props) {
  const { data: namespaces } = useNamespaces()
  const move = useMoveNode()
  const navigate = useNavigate()
  const isFolder = target.type === "folder"
  const currentParent =
    target.type === "folder" ? target.parentId : target.folderId

  const [namespaceId, setNamespaceId] = useState(target.namespaceId)
  const [folderId, setFolderId] = useState<string | null>(currentParent)

  const editable = useMemo(
    () => (namespaces?.data ?? []).filter(canEditNamespace),
    [namespaces],
  )
  // folders can only move inside their own space
  const spaceOptions = isFolder
    ? editable.filter((n) => n.id === target.namespaceId)
    : editable

  const { data: index, isPending } = useQuery(treeQuery(namespaceId))

  const disabled = useMemo(() => {
    if (!index || !isFolder) return new Set<string>()
    return index.descendantIds(target.id)
  }, [index, isFolder, target.id])

  const unchanged =
    namespaceId === target.namespaceId &&
    (folderId ?? null) === (currentParent ?? null)

  const targetNamespace = spaceOptions.find((n) => n.id === namespaceId)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" data-testid="move-dialog">
        <DialogHeader>
          <DialogTitle>
            Move “{target.type === "folder" ? target.name : target.title}”
          </DialogTitle>
          <DialogDescription>
            {isFolder
              ? "Choose a new parent folder inside this space."
              : "Choose a space and folder for this page."}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Select
            value={namespaceId}
            onValueChange={(v) => {
              setNamespaceId(v)
              setFolderId(null)
            }}
            disabled={isFolder}
          >
            <SelectTrigger className="w-full" data-testid="move-space-select">
              <SelectValue placeholder="Select a space" />
            </SelectTrigger>
            <SelectContent>
              {spaceOptions.map((ns) => (
                <SelectItem key={ns.id} value={ns.id}>
                  <span className="flex items-center gap-2">
                    <NamespaceIcon icon={ns.icon} color={ns.color} size="xs" />
                    {ns.name}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <ScrollArea className="h-64 rounded-md border">
            <div className="p-1">
              {isPending || !index ? (
                <div className="flex flex-col gap-2 p-2">
                  {[0, 1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-6 w-full" />
                  ))}
                </div>
              ) : (
                <ul aria-label="Destination folder">
                  <li>
                    <button
                      type="button"
                      aria-pressed={folderId === null}
                      onClick={() => setFolderId(null)}
                      className={cn(
                        "flex h-8 w-full items-center gap-1.5 rounded-md px-2 text-left text-sm hover:bg-accent",
                        folderId === null &&
                          "bg-primary/10 text-primary hover:bg-primary/15",
                      )}
                      data-testid="move-root-option"
                    >
                      <Home className="ml-5 size-4 text-muted-foreground" />
                      <span>{targetNamespace?.name ?? "Space"} (root)</span>
                    </button>
                  </li>
                  {index.childrenOf(null).map((f) => (
                    <FolderOption
                      key={f.id}
                      folder={f}
                      index={index}
                      depth={1}
                      selected={folderId}
                      disabled={disabled}
                      onSelect={setFolderId}
                    />
                  ))}
                </ul>
              )}
            </div>
          </ScrollArea>
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={move.isPending}
          >
            Cancel
          </Button>
          <LoadingButton
            disabled={unchanged}
            loading={move.isPending}
            data-testid="move-submit"
            onClick={() =>
              move.mutate(
                {
                  type: target.type,
                  id: target.id,
                  sourceNamespaceId: target.namespaceId,
                  targetNamespaceId: namespaceId,
                  targetFolderId: folderId,
                },
                {
                  onSuccess: () => {
                    onOpenChange(false)
                    if (
                      target.type === "document" &&
                      namespaceId !== target.namespaceId &&
                      targetNamespace &&
                      window.location.pathname.includes(target.id)
                    ) {
                      navigate({
                        to: "/s/$namespaceSlug/d/$documentId",
                        params: {
                          namespaceSlug: targetNamespace.slug,
                          documentId: target.id,
                        },
                        search: { mode: "view" } as never,
                      })
                    }
                  },
                },
              )
            }
          >
            Move here
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
