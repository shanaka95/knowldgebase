import { useQuery } from "@tanstack/react-query"

import type { NoteKind } from "@/client"
import { NamespaceIcon } from "@/components/Namespaces/NamespaceIcon"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { namespacesQuery } from "@/queries/namespaces"
import { noteTagsQuery } from "@/queries/userNotes"

const ALL_SPACES = "__all__"
const ALL_TAGS = "__all__"

export interface NoteToolbarChange {
  space?: string | undefined
  filter?: "active" | "archived"
  kind?: NoteKind | undefined
  tag?: string | undefined
}

/**
 * Space, archive, kind and tag.
 *
 * Wraps rather than scrolls: the row carries two selects and a toggle group,
 * which does not fit a 320px phone on one line, and a horizontal scroller for
 * controls is a control somebody will not find.
 */
export function NoteToolbar({
  space,
  filter,
  kind,
  tag,
  onChange,
}: {
  space: string | null
  filter: "active" | "archived"
  kind: NoteKind | null
  tag: string | null
  onChange: (next: NoteToolbarChange) => void
}) {
  const spaces = useQuery(namespacesQuery())
  const tags = useQuery(noteTagsQuery())

  return (
    <div
      className="flex min-w-0 flex-wrap items-center gap-2"
      data-testid="notes-toolbar"
    >
      <Select
        value={space ?? ALL_SPACES}
        onValueChange={(value) =>
          onChange({ space: value === ALL_SPACES ? undefined : value })
        }
      >
        <SelectTrigger
          className="h-8 w-full sm:w-56"
          aria-label="Space"
          data-testid="notes-space"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL_SPACES}>Every space</SelectItem>
          {(spaces.data?.data ?? []).map((ns) => (
            <SelectItem key={ns.id} value={ns.id}>
              <span className="flex min-w-0 items-center gap-2">
                <NamespaceIcon icon={ns.icon} color={ns.color} size="xs" />
                <span className="truncate">{ns.name}</span>
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        value={filter}
        onValueChange={(value) => {
          if (value) onChange({ filter: value as "active" | "archived" })
        }}
        aria-label="Show"
        data-testid="notes-filter"
      >
        <ToggleGroupItem value="active">Active</ToggleGroupItem>
        <ToggleGroupItem value="archived">Archived</ToggleGroupItem>
      </ToggleGroup>

      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        value={kind ?? ""}
        onValueChange={(value) =>
          onChange({ kind: (value || undefined) as NoteKind | undefined })
        }
        aria-label="Kind"
        data-testid="notes-kind"
      >
        <ToggleGroupItem value="text">Notes</ToggleGroupItem>
        <ToggleGroupItem value="checklist">Checklists</ToggleGroupItem>
        <ToggleGroupItem value="drawing">Drawings</ToggleGroupItem>
      </ToggleGroup>

      {(tags.data ?? []).length > 0 && (
        <Select
          value={tag ?? ALL_TAGS}
          onValueChange={(value) =>
            onChange({ tag: value === ALL_TAGS ? undefined : value })
          }
        >
          <SelectTrigger
            className="h-8 w-full sm:w-44"
            aria-label="Tag"
            data-testid="notes-tag"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_TAGS}>Every tag</SelectItem>
            {(tags.data ?? []).map((t) => (
              <SelectItem key={t.id} value={t.id}>
                <span className="truncate">{t.name}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </div>
  )
}
