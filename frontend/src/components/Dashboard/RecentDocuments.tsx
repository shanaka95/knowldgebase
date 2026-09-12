import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { FilePlus2, FileText } from "lucide-react"

import { EmbeddingStatusIcon } from "@/components/Embeddings/EmbeddingStatusIcon"
import { EmptyState } from "@/components/Layout/EmptyState"
import { NamespaceIcon } from "@/components/Namespaces/NamespaceIcon"
import { PendingList } from "@/components/Pending/PendingList"
import { useNamespaces } from "@/hooks/useNamespaces"
import { deriveEmbeddingState } from "@/lib/embeddingState"
import { relativeTime } from "@/lib/format"
import { recentDocumentsQuery } from "@/queries/shared"

export function RecentDocuments({ limit = 12 }: { limit?: number }) {
  const { data, isPending } = useQuery(recentDocumentsQuery(limit))
  const { data: namespaces } = useNamespaces()
  const nsById = new Map((namespaces?.data ?? []).map((n) => [n.id, n]))

  if (isPending) return <PendingList rows={5} />
  const docs = data?.data ?? []
  if (docs.length === 0) {
    return (
      <EmptyState
        compact
        icon={FilePlus2}
        title="No recent pages"
        description="Pages you create or edit will show up here."
      />
    )
  }
  return (
    <ul className="divide-y rounded-lg border" data-testid="recent-documents">
      {docs.map((d) => {
        const ns = nsById.get(d.namespace_id)
        const slug = d.namespace_slug ?? ns?.slug
        return (
          <li key={d.id}>
            {slug ? (
              <Link
                to="/s/$namespaceSlug/d/$documentId"
                params={{ namespaceSlug: slug, documentId: d.id }}
                search={{ mode: "view" } as never}
                className="flex items-center gap-3 px-3 py-2.5 transition hover:bg-muted/50"
              >
                <FileText className="size-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {d.title}
                  </span>
                  <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    {ns ? (
                      <>
                        <NamespaceIcon
                          icon={ns.icon}
                          color={ns.color}
                          size="xs"
                        />
                        {ns.name} ·{" "}
                      </>
                    ) : null}
                    updated {relativeTime(d.updated_at)}
                  </span>
                </span>
                <EmbeddingStatusIcon state={deriveEmbeddingState(d)} />
              </Link>
            ) : (
              <div className="flex items-center gap-3 px-3 py-2.5 text-sm">
                <FileText className="size-4 text-muted-foreground" />
                <span className="truncate">{d.title}</span>
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
