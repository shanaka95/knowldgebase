import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { AlertCircle, FileText, Loader2, Puzzle, Search } from "lucide-react"

import type { RetrievalResults } from "@/client"
import { DocumentTypeBadge } from "@/components/Documents/DocumentTypeBadge"
import { EmbeddingStatusIcon } from "@/components/Embeddings/EmbeddingStatusIcon"
import { EmptyState } from "@/components/Layout/EmptyState"
import { NamespaceIcon } from "@/components/Namespaces/NamespaceIcon"
import { PendingList } from "@/components/Pending/PendingList"
import { Button } from "@/components/ui/button"
import { useNamespaces } from "@/hooks/useNamespaces"
import { deriveEmbeddingState } from "@/lib/embeddingState"
import { relativeTime } from "@/lib/format"
import { METHOD_META } from "@/lib/searchPrefs"
import { Snippet } from "@/lib/snippet"
import { searchSuggestionsQuery } from "@/queries/search"
import { SearchExplain } from "./SearchExplain"
import { FusedScore, SourceBadges } from "./SourceBadges"

interface HybridSearchResultsProps {
  query: string
  data: RetrievalResults | undefined
  isPending: boolean
  isFetching: boolean
  error: Error | null
  onRetry: () => void
  requestedBm25: boolean
  requestedVector: boolean
  onEnableBoth: () => void
  /** Puts an example into the search box. */
  onExample?: (query: string) => void
}

export function HybridSearchResults({
  query,
  data,
  isPending,
  isFetching,
  onExample,
  error,
  onRetry,
  requestedBm25,
  requestedVector,
  onEnableBoth,
}: HybridSearchResultsProps) {
  const { data: namespaces } = useNamespaces()
  const nsById = new Map((namespaces?.data ?? []).map((n) => [n.id, n]))

  if (!query) return <SearchIntro onExample={onExample} />

  if (error) {
    return (
      <EmptyState
        icon={AlertCircle}
        title="Search failed"
        description={
          error.message ||
          "Something went wrong running the search. Try again in a moment."
        }
        action={
          <Button variant="outline" onClick={onRetry}>
            Try again
          </Button>
        }
      />
    )
  }

  if (isPending) return <PendingList rows={5} />

  const results = data?.data ?? []
  const onlyOneMethod = !requestedBm25 || !requestedVector

  return (
    <div className="flex flex-col gap-3" data-testid="search-results">
      {data && <SearchExplain result={data} requestedBm25={requestedBm25} />}

      {results.length === 0 ? (
        <EmptyState
          icon={Search}
          title={`No results for “${query}”`}
          description={
            onlyOneMethod
              ? "Try enabling both search methods, widening where to search, or using different words."
              : "Try different words, widen where to search, or check that the pages have finished indexing."
          }
          action={
            onlyOneMethod ? (
              <Button variant="outline" onClick={onEnableBoth}>
                Enable both methods
              </Button>
            ) : undefined
          }
        />
      ) : (
        <>
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            {data?.count} result{data?.count === 1 ? "" : "s"} for “{query}”
            {isFetching && <Loader2 className="size-3.5 animate-spin" />}
          </p>
          <ul className="divide-y rounded-lg border">
            {results.map((hit) => {
              const ns = nsById.get(hit.namespace_id)
              return (
                <li key={hit.document_id}>
                  <Link
                    to="/s/$namespaceSlug/d/$documentId"
                    params={{
                      namespaceSlug: hit.namespace_slug,
                      documentId: hit.document_id,
                    }}
                    search={{ mode: "view" } as never}
                    className="flex items-start gap-3 px-4 py-3 transition hover:bg-muted/50"
                    data-testid="search-result"
                  >
                    <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1">
                      <span className="flex min-w-0 items-center gap-2">
                        <span className="truncate font-medium">
                          {hit.title}
                        </span>
                        <DocumentTypeBadge type={hit.doc_type} />
                        <EmbeddingStatusIcon
                          state={deriveEmbeddingState(hit)}
                        />
                      </span>

                      {hit.matched_chunk_title && (
                        <span className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                          <Puzzle className="size-3" />
                          in section “{hit.matched_chunk_title}”
                        </span>
                      )}

                      <Snippet
                        html={hit.snippet}
                        className="mt-1 line-clamp-3 block text-sm text-muted-foreground"
                      />

                      <span className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1.5">
                        <SourceBadges sources={hit.sources ?? []} />
                      </span>

                      <span className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                        <NamespaceIcon
                          icon={ns?.icon}
                          color={ns?.color}
                          size="xs"
                        />
                        {hit.namespace_name}
                        {hit.updated_at && (
                          <> · updated {relativeTime(hit.updated_at)}</>
                        )}
                      </span>
                    </span>
                    <FusedScore score={hit.score} k={data?.rrf_k ?? 60} />
                  </Link>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}

function SearchIntro({ onExample }: { onExample?: (q: string) => void }) {
  const { data } = useQuery(searchSuggestionsQuery())
  const suggestions = data?.data ?? []

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-dashed px-6 py-8">
      <div>
        <h2 className="text-base font-medium">Search your knowledge base</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Two kinds of search run at once and their rankings are merged, so
          exact wording and meaning both count.
        </p>
      </div>
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {(["bm25", "vector"] as const).map((method) => {
          const meta = METHOD_META[method]
          return (
            <div key={method} className="rounded-md border bg-muted/20 p-3">
              <dt className="flex items-center gap-1.5 text-sm font-medium">
                <span
                  className={`size-2 rounded-full ${meta.dot}`}
                  aria-hidden
                />
                {meta.label}
                <span className="font-normal text-muted-foreground">
                  ({meta.sublabel})
                </span>
              </dt>
              <dd className="mt-1 text-sm text-muted-foreground">
                {meta.hint}
              </dd>
            </div>
          )
        })}
      </dl>

      {suggestions.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground">
            Try one of yours
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {suggestions.map((suggestion) => (
              <Button
                key={suggestion.question}
                variant="outline"
                size="sm"
                // A generated question can be long, and a button is
                // `whitespace-nowrap` by default - which pushed the page
                // sideways on a phone rather than wrapping.
                className="h-auto max-w-full whitespace-normal py-1.5 text-left"
                onClick={() => onExample?.(suggestion.question)}
                data-testid="search-suggestion"
              >
                {suggestion.question}
              </Button>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Written from your own pages as they were added, and only ever shown
            to you.
          </p>
        </div>
      )}
    </div>
  )
}
