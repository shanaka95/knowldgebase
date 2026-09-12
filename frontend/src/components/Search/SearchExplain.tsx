import { AlertTriangle, ChevronRight, Info } from "lucide-react"
import { useState } from "react"

import type { RetrievalResults } from "@/client"
import { Badge } from "@/components/ui/badge"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { methodMeta, targetLabel } from "@/lib/searchPrefs"
import { cn } from "@/lib/utils"

/**
 * "How these results were ranked" — per-source timings and hit counts, the
 * tokens BM25 actually searched for, and any source that failed.
 */
export function SearchExplain({
  result,
  requestedBm25,
}: {
  result: RetrievalResults
  requestedBm25: boolean
}) {
  const [open, setOpen] = useState(false)
  const sources = result.sources ?? []
  const failed = sources.filter((s) => s.error)
  const tokens = result.query_tokens ?? []
  // The server drops BM25 when the query has no searchable terms left.
  const bm25Skipped = requestedBm25 && !result.used_bm25

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="rounded-lg border bg-muted/20"
    >
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm text-muted-foreground transition hover:text-foreground">
        <ChevronRight
          className={cn("size-4 transition-transform", open && "rotate-90")}
        />
        <Info className="size-3.5" />
        How these results were ranked
        <span className="ml-auto flex items-center gap-2 text-xs">
          {(failed.length > 0 || bm25Skipped) && (
            <Badge
              variant="outline"
              className="gap-1 border-warning/40 bg-warning/15 font-normal text-foreground"
            >
              <AlertTriangle className="size-3" />
              {failed.length > 0 ? `${failed.length} failed` : "no keywords"}
            </Badge>
          )}
          <span className="font-mono tabular-nums">
            {Math.round(result.took_ms ?? 0)} ms
          </span>
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="flex flex-col gap-4 border-t px-4 py-3 text-sm">
          {result.used_rerank && (
            <p className="text-foreground">
              A reranker read your query against each of the top results and put
              them in this order. Fusion decided which pages made the shortlist;
              the reranker decided which of them come first.
            </p>
          )}
          {bm25Skipped && (
            <p className="flex items-start gap-2 text-foreground">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" />
              <span>
                Keyword search was skipped: the query has no searchable terms
                left after removing very common words. Only semantic search ran.
              </span>
            </p>
          )}

          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-muted-foreground">
            <span>
              Fusion constant k ={" "}
              <span className="font-mono text-foreground">{result.rrf_k}</span>
            </span>
            <span>
              Reranking:{" "}
              <span className="text-foreground">
                {result.used_rerank ? "on" : "off"}
              </span>
            </span>
            <span>
              Searched in{" "}
              {(result.targets ?? []).map((t, i) => (
                <span key={t}>
                  {i > 0 && ", "}
                  <span className="text-foreground">
                    {targetLabel(t).toLowerCase()}
                  </span>
                </span>
              ))}
            </span>
            {tokens.length > 0 && (
              <span className="flex flex-wrap items-center gap-1">
                Keywords:
                {tokens.map((t) => (
                  <Badge
                    key={t}
                    variant="secondary"
                    className="font-mono font-normal"
                  >
                    {t}
                  </Badge>
                ))}
              </span>
            )}
          </div>

          {sources.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-muted-foreground">
                  <tr className="border-b">
                    <th className="py-1.5 pr-4 text-left font-medium">
                      Source
                    </th>
                    <th className="py-1.5 pr-4 text-left font-medium">
                      Searched in
                    </th>
                    <th className="py-1.5 pr-4 text-right font-medium">Hits</th>
                    <th className="py-1.5 text-right font-medium">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.map((s) => {
                    const meta = methodMeta(s.method)
                    return (
                      <tr
                        key={`${s.method}-${s.target}`}
                        className="border-b last:border-0"
                        data-testid="explain-row"
                      >
                        <td className="py-1.5 pr-4">
                          <span className="flex items-center gap-1.5">
                            <span
                              className={cn("size-2 rounded-full", meta.dot)}
                              aria-hidden
                            />
                            {meta.label}
                          </span>
                        </td>
                        <td className="py-1.5 pr-4">
                          {targetLabel(s.target)}
                          {s.error && (
                            <span className="mt-0.5 flex items-start gap-1 text-foreground">
                              <AlertTriangle className="mt-0.5 size-3 shrink-0 text-warning" />
                              {s.error}
                            </span>
                          )}
                        </td>
                        <td className="py-1.5 pr-4 text-right font-mono tabular-nums">
                          {s.error ? "—" : s.hits}
                        </td>
                        <td className="py-1.5 text-right font-mono text-muted-foreground tabular-nums">
                          {Math.round(s.took_ms)} ms
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          <p className="text-xs text-muted-foreground">
            Each source ranks pages on its own. Ranks — not scores — are then
            fused: a page gets 1 / (k + rank) from every source that found it,
            so agreement across methods outranks a single strong match.
          </p>
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
