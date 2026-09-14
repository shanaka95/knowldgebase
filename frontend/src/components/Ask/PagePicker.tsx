import { useQuery } from "@tanstack/react-query"
import { FileText, Loader2, Pin } from "lucide-react"
import { useState } from "react"

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { useSearch } from "@/hooks/useSearch"
import { recentDocumentsQuery } from "@/queries/shared"

export interface PickedPage {
  id: string
  title: string
}

interface PagePickerProps {
  onPick: (page: PickedPage) => void
  children: React.ReactNode
}

/**
 * Choose the page a question is about.
 *
 * Backed by Postgres full-text search rather than the hybrid retrieval the
 * answer itself uses: this is a name lookup, and it has to feel like typing in
 * a file dialog. Recent pages fill the list before anything is typed, because
 * the page somebody wants to ask about is usually the one they just had open.
 */
export function PagePicker({ onPick, children }: PagePickerProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const { data, isFetching, debouncedQuery } = useSearch(query)
  const { data: recent, isPending: recentPending } = useQuery({
    ...recentDocumentsQuery(8),
    enabled: open,
  })

  const searching = debouncedQuery.length > 0
  // "Nothing here" is only true once something has been looked for.
  const looking = searching ? isFetching : recentPending
  const results = searching
    ? (data?.data ?? []).map((r) => ({
        id: r.document_id,
        title: r.title,
        where: r.namespace_name,
      }))
    : (recent?.data ?? []).map((d) => ({
        id: d.id,
        title: d.title,
        where: d.namespace_name ?? "",
      }))

  const pick = (page: PickedPage) => {
    onPick(page)
    setOpen(false)
    setQuery("")
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent
        className="w-[min(26rem,calc(100vw-2rem))] p-0"
        align="start"
      >
        <Command shouldFilter={false}>
          <CommandInput
            placeholder="Find a page to ask about…"
            value={query}
            onValueChange={setQuery}
            data-testid="ask-page-picker-input"
          />
          <CommandList className="max-h-72">
            {looking && (
              <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" />
                {searching ? "Searching…" : "Loading…"}
              </div>
            )}
            {!looking && results.length === 0 && (
              <CommandEmpty>
                {searching
                  ? `No pages match “${debouncedQuery}”.`
                  : "No pages yet."}
              </CommandEmpty>
            )}
            {results.length > 0 && (
              <CommandGroup heading={searching ? "Pages" : "Recent"}>
                {results.map((page) => (
                  <CommandItem
                    key={page.id}
                    value={page.id}
                    onSelect={() => pick({ id: page.id, title: page.title })}
                    className="items-start gap-2.5 py-2"
                    data-testid="ask-page-option"
                  >
                    <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{page.title}</span>
                      {page.where && (
                        <span className="block truncate text-xs text-muted-foreground">
                          {page.where}
                        </span>
                      )}
                    </span>
                    <Pin className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
