import { useQuery } from "@tanstack/react-query"
import { CornerDownRight } from "lucide-react"

import type { NamespacePublic } from "@/client"
import { NamespaceIcon } from "@/components/Namespaces/NamespaceIcon"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { foldersInTreeOrder, treeQuery } from "@/queries/namespaces"

/**
 * Where a document is about to land: which space, and which folder in it.
 *
 * One component rather than one per way of getting a file in, because the
 * answer to "where does this go" should not depend on whether the file came
 * from a phone camera, a file picker or a Drive - and a folder hierarchy that
 * reads correctly in one place and not the other is worse than either.
 */
export function DestinationFields({
  spaces,
  spaceId,
  onSpaceChange,
  folderId,
  onFolderChange,
  disabled = false,
  idPrefix = "destination",
}: {
  spaces: NamespacePublic[]
  spaceId: string
  onSpaceChange: (id: string) => void
  folderId: string | null
  onFolderChange: (id: string | null) => void
  disabled?: boolean
  idPrefix?: string
}) {
  const { data: tree } = useQuery({
    ...treeQuery(spaceId),
    enabled: Boolean(spaceId),
  })
  const folders = tree?.raw.folders ?? []

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div className="flex flex-col gap-2">
        <Label htmlFor={`${idPrefix}-space`}>Space</Label>
        <Select
          value={spaceId}
          onValueChange={(value) => {
            onSpaceChange(value)
            onFolderChange(null)
          }}
          disabled={disabled}
        >
          <SelectTrigger
            id={`${idPrefix}-space`}
            className="w-full"
            data-testid={`${idPrefix}-space-select`}
          >
            <SelectValue placeholder="Select a space" />
          </SelectTrigger>
          <SelectContent>
            {spaces.map((ns) => (
              <SelectItem key={ns.id} value={ns.id}>
                <span className="flex items-center gap-2">
                  <NamespaceIcon icon={ns.icon} color={ns.color} size="xs" />
                  {ns.name}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor={`${idPrefix}-folder`}>Folder</Label>
        <Select
          value={folderId ?? "__root__"}
          onValueChange={(value) =>
            onFolderChange(value === "__root__" ? null : value)
          }
          disabled={disabled}
        >
          <SelectTrigger
            id={`${idPrefix}-folder`}
            className="w-full"
            data-testid={`${idPrefix}-folder-select`}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__root__">Space root</SelectItem>
            {/*
              Indented by depth, so a nested folder reads as nested. A flat
              list cannot distinguish a top-level "Invoices" from one of three
              under different parents, which leaves the reader guessing where a
              document is about to go.
            */}
            {foldersInTreeOrder(folders).map(({ folder, depth }) => (
              <SelectItem key={folder.id} value={folder.id}>
                <span
                  style={{ paddingInlineStart: `${depth * 14}px` }}
                  className="flex min-w-0 items-center gap-1.5"
                >
                  {depth > 0 && (
                    <CornerDownRight
                      className="size-3 shrink-0 text-muted-foreground"
                      aria-hidden
                    />
                  )}
                  <span className="truncate">{folder.name}</span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  )
}
