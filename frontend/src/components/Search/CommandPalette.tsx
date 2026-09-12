import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import {
  FilePlus2,
  FileText,
  FolderKanban,
  Home,
  Loader2,
  Moon,
  Search,
  Settings,
  Sparkles,
  Sun,
} from "lucide-react"
import { useEffect, useState } from "react"

import type { SearchResult } from "@/client"
import { DocumentTypeBadge } from "@/components/Documents/DocumentTypeBadge"
import { EmbeddingStatusIcon } from "@/components/Embeddings/EmbeddingStatusIcon"
import { NamespaceIcon } from "@/components/Namespaces/NamespaceIcon"
import { useTheme } from "@/components/theme-provider"
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command"
import { useCreateDocument } from "@/hooks/useKbMutations"
import { canEditNamespace, useActiveNamespace } from "@/hooks/useNamespaces"
import { useSearch } from "@/hooks/useSearch"
import { deriveEmbeddingState } from "@/lib/embeddingState"
import { Snippet } from "@/lib/snippet"
import { recentDocumentsQuery } from "@/queries/shared"
import { useSearchDialogStore } from "@/stores/searchDialog"

export function CommandPalette() {
  const isOpen = useSearchDialogStore((s) => s.isOpen)
  const setOpen = useSearchDialogStore((s) => s.setOpen)
  const toggle = useSearchDialogStore((s) => s.toggle)
  const navigate = useNavigate()
  const { theme, setTheme } = useTheme()
  const { active, namespaces } = useActiveNamespace()
  const createDocument = useCreateDocument()
  const [query, setQuery] = useState("")
  const { data, isFetching, debouncedQuery } = useSearch(query)
  const { data: recent } = useQuery({
    ...recentDocumentsQuery(8),
    enabled: isOpen,
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        toggle()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [toggle])

  useEffect(() => {
    if (!isOpen) setQuery("")
  }, [isOpen])

  const nsById = new Map(namespaces.map((n) => [n.id, n]))
  const run = (fn: () => void) => {
    setOpen(false)
    fn()
  }
  const openResult = (r: SearchResult) =>
    run(() =>
      navigate({
        to: "/s/$namespaceSlug/d/$documentId",
        params: { namespaceSlug: r.namespace_slug, documentId: r.document_id },
        search: { mode: "view" } as never,
      }),
    )

  const grouped = new Map<string, SearchResult[]>()
  for (const r of data?.data ?? []) {
    const list = grouped.get(r.namespace_id) ?? []
    list.push(r)
    grouped.set(r.namespace_id, list)
  }
  const searching = debouncedQuery.length > 0

  /*
   * cmdk keeps whatever it highlighted first. While a search is still in
   * flight the pinned "Search everything" row is the only item, so without
   * this the highlight sticks there and Enter would leave the page you were
   * looking for behind.
   */
  const [selected, setSelected] = useState("")
  const firstResultId = data?.data?.[0]?.document_id
  useEffect(() => {
    if (searching) setSelected(firstResultId ?? "see-all")
  }, [searching, firstResultId])

  return (
    <CommandDialog
      open={isOpen}
      onOpenChange={setOpen}
      title="Search"
      description="Search pages or jump to an action"
      shouldFilter={!searching}
      value={searching ? selected : undefined}
      onValueChange={setSelected}
      className="sm:max-w-2xl"
    >
      <CommandInput
        placeholder="Search pages by title or content…"
        value={query}
        onValueChange={setQuery}
        data-testid="command-input"
      />
      <CommandList className="max-h-[60vh]">
        {searching ? (
          <>
            {isFetching && (
              <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" /> Searching…
              </div>
            )}
            {!isFetching && (data?.count ?? 0) === 0 && (
              <CommandEmpty>No pages match “{debouncedQuery}”.</CommandEmpty>
            )}
            {[...grouped.entries()].map(([nsId, results]) => {
              const ns = nsById.get(nsId)
              return (
                <CommandGroup
                  key={nsId}
                  heading={
                    <span className="flex items-center gap-1.5">
                      {ns && (
                        <NamespaceIcon
                          icon={ns.icon}
                          color={ns.color}
                          size="xs"
                        />
                      )}
                      {results[0].namespace_name}
                    </span>
                  }
                >
                  {results.map((r) => (
                    <CommandItem
                      key={r.document_id}
                      value={`${r.document_id}`}
                      onSelect={() => openResult(r)}
                      className="items-start gap-3 py-2"
                      data-testid="command-result"
                    >
                      <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1">
                        <span className="flex min-w-0 items-center gap-2">
                          <span className="truncate font-medium">
                            {r.title}
                          </span>
                          <DocumentTypeBadge type={r.doc_type} />
                          <EmbeddingStatusIcon
                            state={deriveEmbeddingState(r)}
                          />
                        </span>
                        <Snippet
                          html={r.snippet}
                          className="line-clamp-2 text-xs text-muted-foreground"
                        />
                      </span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              )
            })}
            <CommandSeparator />
            <CommandGroup>
              {/* Always offered: the palette does a fast title/content lookup,
                  the search page adds semantic matching on top. */}
              <CommandItem
                value="see-all"
                onSelect={() =>
                  run(() =>
                    navigate({
                      to: "/search",
                      search: { q: debouncedQuery },
                    }),
                  )
                }
                data-testid="command-search-everything"
              >
                <Search className="size-4" />
                <span className="truncate">
                  Search everything for “{debouncedQuery}”
                </span>
                <span className="ml-auto flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">
                    keyword + semantic
                  </span>
                  <CommandShortcut>↵</CommandShortcut>
                </span>
              </CommandItem>
              {/* Same retrieval, but the model writes the answer. */}
              <CommandItem
                value="ask-everything"
                onSelect={() =>
                  run(() =>
                    navigate({
                      to: "/ask",
                      search: { q: debouncedQuery },
                    }),
                  )
                }
                data-testid="command-ask"
              >
                <Sparkles className="size-4" />
                <span className="truncate">Ask about “{debouncedQuery}”</span>
                <span className="ml-auto text-xs text-muted-foreground">
                  answered with citations
                </span>
              </CommandItem>
            </CommandGroup>
          </>
        ) : (
          <>
            <CommandEmpty>Nothing found.</CommandEmpty>
            {(recent?.data.length ?? 0) > 0 && (
              <CommandGroup heading="Recent pages">
                {recent?.data.map((d) => {
                  const ns = nsById.get(d.namespace_id)
                  if (!ns) return null
                  return (
                    <CommandItem
                      key={d.id}
                      value={`recent-${d.id} ${d.title}`}
                      onSelect={() =>
                        run(() =>
                          navigate({
                            to: "/s/$namespaceSlug/d/$documentId",
                            params: {
                              namespaceSlug: ns.slug,
                              documentId: d.id,
                            },
                            search: { mode: "view" } as never,
                          }),
                        )
                      }
                    >
                      <FileText className="size-4 text-muted-foreground" />
                      <span className="truncate">{d.title}</span>
                      <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
                        <NamespaceIcon
                          icon={ns.icon}
                          color={ns.color}
                          size="xs"
                        />
                        {ns.name}
                      </span>
                    </CommandItem>
                  )
                })}
              </CommandGroup>
            )}
            <CommandSeparator />
            <CommandGroup heading="Actions">
              {active && canEditNamespace(active) && (
                <CommandItem
                  value="new page"
                  onSelect={() =>
                    run(() =>
                      createDocument.mutate({
                        namespaceId: active.id,
                        namespaceSlug: active.slug,
                        folderId: null,
                      }),
                    )
                  }
                >
                  <FilePlus2 className="size-4" />
                  New page in {active.name}
                </CommandItem>
              )}
              <CommandItem
                value="dashboard home"
                onSelect={() => run(() => navigate({ to: "/" }))}
              >
                <Home className="size-4" />
                Go to dashboard
              </CommandItem>
              {active && (
                <CommandItem
                  value={`space ${active.name}`}
                  onSelect={() =>
                    run(() =>
                      navigate({
                        to: "/s/$namespaceSlug",
                        params: { namespaceSlug: active.slug },
                      }),
                    )
                  }
                >
                  <FolderKanban className="size-4" />
                  Open space {active.name}
                </CommandItem>
              )}
              <CommandItem
                value="settings"
                onSelect={() =>
                  run(() =>
                    navigate({ to: "/settings", search: { tab: "profile" } }),
                  )
                }
              >
                <Settings className="size-4" />
                Settings
              </CommandItem>
              <CommandItem
                value="toggle theme dark light"
                onSelect={() =>
                  run(() => setTheme(theme === "dark" ? "light" : "dark"))
                }
              >
                {theme === "dark" ? (
                  <Sun className="size-4" />
                ) : (
                  <Moon className="size-4" />
                )}
                Toggle theme
              </CommandItem>
            </CommandGroup>
          </>
        )}
      </CommandList>
    </CommandDialog>
  )
}
