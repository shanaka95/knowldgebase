import { useQuery } from "@tanstack/react-query"
import { ChevronRight, Folder, FolderOpen, Home } from "lucide-react"
import { useState } from "react"

import type { FolderPublic, NamespacePublic } from "@/client"
import { NamespaceIcon } from "@/components/Namespaces/NamespaceIcon"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { type TreeIndex, treeQuery } from "@/queries/namespaces"

interface DestinationPickerProps {
  /** Spaces the caller considers eligible; the first is not chosen for you. */
  spaces: NamespacePublic[]
  namespaceId: string
  onNamespaceChange: (namespaceId: string) => void
  folderId: string | null
  onFolderChange: (folderId: string | null) => void
  /** Folders that may not be chosen — a folder cannot move inside itself. */
  disabledFolderIds?: Set<string>
  /** Locks the space picker (folders never leave their own space). */
  lockSpace?: boolean
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
          "flex h-8 min-w-0 items-center gap-1 rounded-md pr-2 text-sm",
          isSelected && "bg-primary/10 text-primary",
          !isSelected && !isDisabled && "hover:bg-accent",
          isDisabled && "opacity-40",
        )}
        style={{ paddingLeft: `${depth * 16 + 4}px` }}
        data-testid="destination-folder-option"
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

/**
 * "Which space, and which folder in it" — shared by moving a page and copying
 * one, because the question and the answer are identical in both.
 */
export function DestinationPicker({
  spaces,
  namespaceId,
  onNamespaceChange,
  folderId,
  onFolderChange,
  disabledFolderIds,
  lockSpace,
}: DestinationPickerProps) {
  const { data: index, isPending } = useQuery(treeQuery(namespaceId))
  const selectedSpace = spaces.find((n) => n.id === namespaceId)
  const disabled = disabledFolderIds ?? new Set<string>()

  return (
    <div className="flex flex-col gap-3">
      <Select
        value={namespaceId}
        onValueChange={onNamespaceChange}
        disabled={lockSpace}
      >
        <SelectTrigger
          className="w-full"
          data-testid="destination-space-select"
        >
          <SelectValue placeholder="Select a space" />
        </SelectTrigger>
        <SelectContent>
          {spaces.map((ns) => (
            <SelectItem key={ns.id} value={ns.id}>
              {/* Cloned into the closed trigger, where the space name has only
                  the width of a phone to fit in. */}
              <span className="flex min-w-0 items-center gap-2">
                <NamespaceIcon icon={ns.icon} color={ns.color} size="xs" />
                <span className="truncate">{ns.name}</span>
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
                  onClick={() => onFolderChange(null)}
                  className={cn(
                    "flex h-8 w-full items-center gap-1.5 rounded-md px-2 text-left text-sm hover:bg-accent",
                    folderId === null &&
                      "bg-primary/10 text-primary hover:bg-primary/15",
                  )}
                  data-testid="destination-root-option"
                >
                  <Home className="ml-5 size-4 shrink-0 text-muted-foreground" />
                  <span className="truncate">
                    {selectedSpace?.name ?? "Space"} (root)
                  </span>
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
                  onSelect={onFolderChange}
                />
              ))}
            </ul>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
