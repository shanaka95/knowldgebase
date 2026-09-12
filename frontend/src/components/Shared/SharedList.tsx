import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { FileText, Share2 } from "lucide-react"

import { EmbeddingStatusIcon } from "@/components/Embeddings/EmbeddingStatusIcon"
import { EmptyState } from "@/components/Layout/EmptyState"
import { NamespaceIcon } from "@/components/Namespaces/NamespaceIcon"
import { RoleBadge } from "@/components/Namespaces/RoleBadge"
import { PendingList } from "@/components/Pending/PendingList"
import { useNamespaces } from "@/hooks/useNamespaces"
import { deriveEmbeddingState } from "@/lib/embeddingState"
import { relativeTime } from "@/lib/format"
import { sharedWithMeQuery } from "@/queries/shared"

export function SharedList() {
  const { data, isPending } = useQuery(sharedWithMeQuery())
  const { data: namespaces } = useNamespaces()
  const nsById = new Map((namespaces?.data ?? []).map((n) => [n.id, n]))

  if (isPending) return <PendingList />
  const spaces = data?.namespaces ?? []
  const docs = data?.documents ?? []
  if (spaces.length === 0 && docs.length === 0) {
    return (
      <EmptyState
        icon={Share2}
        title="Nothing shared yet"
        description="When someone shares a space or a page with you it will appear here."
      />
    )
  }
  return (
    <div className="flex flex-col gap-8" data-testid="shared-list">
      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">
          Spaces ({spaces.length})
        </h2>
        {spaces.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No spaces have been shared with you.
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {spaces.map((ns) => (
              <Link
                key={ns.id}
                to="/s/$namespaceSlug"
                params={{ namespaceSlug: ns.slug }}
                className="flex items-start gap-3 rounded-lg border bg-card p-4 transition hover:border-primary/40 hover:shadow-sm"
              >
                <NamespaceIcon icon={ns.icon} color={ns.color} />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium">
                      {ns.name}
                    </span>
                    <RoleBadge role={ns.my_role} />
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {ns.owner?.full_name || ns.owner?.email
                      ? `Owned by ${ns.owner.full_name || ns.owner.email}`
                      : `${ns.document_count ?? 0} pages`}
                  </span>
                </span>
              </Link>
            ))}
          </div>
        )}
      </section>
      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground">
          Pages ({docs.length})
        </h2>
        {docs.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No individual pages have been shared with you.
          </p>
        ) : (
          <ul className="divide-y rounded-lg border">
            {docs.map((d) => {
              const ns = nsById.get(d.namespace_id)
              return (
                <li key={d.id}>
                  <Link
                    to="/s/$namespaceSlug/d/$documentId"
                    params={{
                      namespaceSlug: d.namespace_slug ?? ns?.slug ?? "shared",
                      documentId: d.id,
                    }}
                    search={{ mode: "view" } as never}
                    className="flex items-center gap-3 px-3 py-2.5 transition hover:bg-muted/50"
                    data-testid="shared-document"
                  >
                    <FileText className="size-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium">
                          {d.title}
                        </span>
                        <RoleBadge role={d.my_role} />
                      </span>
                      <span className="text-xs text-muted-foreground">
                        updated {relativeTime(d.updated_at)}
                      </span>
                    </span>
                    <EmbeddingStatusIcon state={deriveEmbeddingState(d)} />
                  </Link>
                </li>
              )
            })}
          </ul>
        )}
      </section>
    </div>
  )
}
