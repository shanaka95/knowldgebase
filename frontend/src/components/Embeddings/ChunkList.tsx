import { ChevronRight, Scissors } from "lucide-react"
import { useState } from "react"

import type { DocumentChunkPublic } from "@/client"
import { Badge } from "@/components/ui/badge"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { cn } from "@/lib/utils"
import { chunkingMethodLabel } from "./chunkingMethodLabels"

interface ChunkListProps {
  chunks: DocumentChunkPublic[]
  method: string | null | undefined
}

export function ChunkList({ chunks, method }: ChunkListProps) {
  return (
    <section
      className="rounded-lg border bg-card p-3"
      aria-labelledby="ai-chunks-heading"
      data-testid="ai-chunks"
    >
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <h4
          id="ai-chunks-heading"
          className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground"
        >
          <Scissors className="size-3.5" />
          Chunks
          <Badge variant="secondary" className="h-4 px-1.5 text-[10px]">
            {chunks.length}
          </Badge>
        </h4>
        <span className="text-[11px] text-muted-foreground">
          {chunkingMethodLabel(method)}
        </span>
      </div>
      {chunks.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {method === "llm_single_topic"
            ? "The page covers a single topic, so it is indexed as one piece."
            : method === "none_short"
              ? "The page is too short to split."
              : "No chunks for the indexed version."}
        </p>
      ) : (
        <ul className="flex flex-col divide-y">
          {chunks.map((chunk) => (
            <ChunkRow
              key={`${chunk.doc_version}-${chunk.chunk_index}`}
              chunk={chunk}
            />
          ))}
        </ul>
      )}
    </section>
  )
}

function ChunkRow({ chunk }: { chunk: DocumentChunkPublic }) {
  const [open, setOpen] = useState(false)
  return (
    <li>
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="group flex w-full items-start gap-2 py-2 text-left">
          <ChevronRight
            className={cn(
              "mt-0.5 size-3.5 shrink-0 text-muted-foreground transition-transform",
              open && "rotate-90",
            )}
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="min-w-0 truncate text-sm font-medium">
                {chunk.title || `Chunk ${chunk.chunk_index + 1}`}
              </span>
              <span className="ml-auto shrink-0 text-[10px] tabular-nums text-muted-foreground">
                {chunk.char_count.toLocaleString()} chars
              </span>
            </div>
            {!open && (
              <p className="line-clamp-2 text-xs text-muted-foreground">
                {chunk.text}
              </p>
            )}
          </div>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <p className="whitespace-pre-wrap pb-3 pl-5.5 text-xs leading-relaxed text-foreground/90">
            {chunk.text}
          </p>
        </CollapsibleContent>
      </Collapsible>
    </li>
  )
}

export default ChunkList
