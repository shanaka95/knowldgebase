import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import { z } from "zod"

import { PageContainer, PageHeader } from "@/components/Layout/PageContainer"
import { HybridSearchResults } from "@/components/Search/HybridSearchResults"
import { SearchControls } from "@/components/Search/SearchControls"
import { useHybridSearch } from "@/hooks/useSearch"
import {
  clampCandidates,
  clampK,
  DEFAULT_PREFS,
  parseTargets,
  readSearchPrefs,
  type SearchTarget,
  serializeTargets,
  writeSearchPrefs,
} from "@/lib/searchPrefs"

export const Route = createFileRoute("/_layout/search")({
  component: SearchPage,
  staticData: { crumb: "Search" },
  validateSearch: z.object({
    q: z.string().catch(""),
    space: z.string().optional().catch(undefined),
    // Undefined means "use the remembered preference"; an explicit value in the
    // URL always wins, which is what makes a shared link reproduce the search.
    bm25: z.boolean().optional().catch(undefined),
    vector: z.boolean().optional().catch(undefined),
    targets: z.string().optional().catch(undefined),
    pages: z.boolean().optional().catch(undefined),
    notes: z.boolean().optional().catch(undefined),
    k: z.number().optional().catch(undefined),
    depth: z.number().optional().catch(undefined),
  }),
  head: () => ({ meta: [{ title: "Search - PlusGPT" }] }),
})

function SearchPage() {
  const search = Route.useSearch()
  const { q, space } = search
  const navigate = useNavigate({ from: Route.fullPath })
  const [value, setValue] = useState(q)

  // Remembered settings fill in whatever the URL does not specify.
  const storedRef = useRef(readSearchPrefs())
  const stored = storedRef.current

  const bm25 = search.bm25 ?? stored.bm25
  const vectorRaw = search.vector ?? stored.vector
  // Guard against a hand-edited URL turning both methods off.
  const vector = bm25 || vectorRaw ? vectorRaw : true
  const targets =
    search.targets !== undefined ? parseTargets(search.targets) : stored.targets
  const pagesRaw = search.pages ?? stored.pages
  const notes = search.notes ?? stored.notes
  // The same guard the methods get: searching neither corpus is a 422.
  const pages = pagesRaw || notes ? pagesRaw : true
  const rrfK = search.k !== undefined ? clampK(search.k) : stored.rrfK
  const candidates =
    search.depth !== undefined
      ? clampCandidates(search.depth)
      : stored.candidates

  useEffect(() => setValue(q), [q])

  useEffect(() => {
    writeSearchPrefs({ bm25, vector, targets, pages, notes, rrfK, candidates })
  }, [bm25, vector, targets, pages, notes, rrfK, candidates])

  // Keep the query in the URL so results are shareable and the back button works.
  useEffect(() => {
    const t = window.setTimeout(() => {
      if (value !== q)
        navigate({ search: (prev) => ({ ...prev, q: value }), replace: true })
    }, 300)
    return () => window.clearTimeout(t)
  }, [value, q, navigate])

  const patch = (next: Partial<typeof search>) =>
    navigate({ search: (prev) => ({ ...prev, ...next }), replace: true })

  const { data, isPending, isFetching, error, refetch, debouncedQuery } =
    useHybridSearch({
      q: value,
      bm25,
      pages,
      notes,
      vector,
      targets,
      namespaceId: space,
      rrfK,
      candidates,
    })

  return (
    <PageContainer className="flex flex-col gap-6" size="default">
      <PageHeader
        title="Search"
        description="Keyword and semantic search run together; their rankings are fused so both exact wording and meaning count."
      />

      <SearchControls
        value={value}
        onValueChange={setValue}
        onSubmit={() => patch({ q: value })}
        bm25={bm25}
        vector={vector}
        onMethodChange={(method, enabled) =>
          patch(method === "bm25" ? { bm25: enabled } : { vector: enabled })
        }
        targets={targets}
        onTargetsChange={(next: SearchTarget[]) =>
          patch({ targets: serializeTargets(next) })
        }
        pages={pages}
        notes={notes}
        onCorpusChange={(corpus, enabled) =>
          patch(corpus === "pages" ? { pages: enabled } : { notes: enabled })
        }
        space={space}
        onSpaceChange={(next) => patch({ space: next })}
        rrfK={rrfK}
        onRrfKChange={(k) => patch({ k: clampK(k) })}
        candidates={candidates}
        onCandidatesChange={(n) => patch({ depth: clampCandidates(n) })}
        onReset={() =>
          patch({
            k: DEFAULT_PREFS.rrfK,
            depth: DEFAULT_PREFS.candidates,
          })
        }
      />

      <HybridSearchResults
        query={debouncedQuery}
        data={data}
        isPending={isPending && debouncedQuery.length > 0}
        isFetching={isFetching}
        error={error}
        onRetry={() => void refetch()}
        requestedBm25={bm25}
        requestedVector={vector}
        onEnableBoth={() => patch({ bm25: true, vector: true })}
        onExample={(example) => {
          setValue(example)
          patch({ q: example })
        }}
      />
    </PageContainer>
  )
}
