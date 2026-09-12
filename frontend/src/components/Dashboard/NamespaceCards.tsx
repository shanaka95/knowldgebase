import { Link } from "@tanstack/react-router"
import { FolderKanban, Plus } from "lucide-react"

import { EmptyState } from "@/components/Layout/EmptyState"
import { NamespaceIcon } from "@/components/Namespaces/NamespaceIcon"
import { RoleBadge } from "@/components/Namespaces/RoleBadge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useNamespaces } from "@/hooks/useNamespaces"
import { openDialog } from "@/stores/dialogs"

export function NamespaceCards() {
  const { data, isPending } = useNamespaces()
  if (isPending) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-24 w-full" />
        ))}
      </div>
    )
  }
  const spaces = data?.data ?? []
  if (spaces.length === 0) {
    return (
      <EmptyState
        compact
        icon={FolderKanban}
        title="No spaces yet"
        description="Spaces group your pages — create one for personal notes and one for work."
        action={
          <Button
            onClick={() => openDialog({ kind: "createNamespace" })}
            data-testid="dashboard-create-space"
          >
            <Plus />
            Create a space
          </Button>
        }
      />
    )
  }
  return (
    <div
      className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
      data-testid="namespace-cards"
    >
      {spaces.map((ns) => (
        <Link
          key={ns.id}
          to="/s/$namespaceSlug"
          params={{ namespaceSlug: ns.slug }}
          className="flex items-start gap-3 rounded-lg border bg-card p-4 transition hover:border-primary/40 hover:shadow-sm"
        >
          <NamespaceIcon icon={ns.icon} color={ns.color} size="md" />
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2">
              <span className="min-w-0 truncate text-sm font-medium">
                {ns.name}
              </span>
              <RoleBadge role={ns.my_role} />
            </span>
            <span className="mt-0.5 block truncate text-xs text-muted-foreground">
              {ns.description || `${ns.document_count ?? 0} pages`}
            </span>
          </span>
        </Link>
      ))}
      <button
        type="button"
        onClick={() => openDialog({ kind: "createNamespace" })}
        className="flex items-center justify-center gap-2 rounded-lg border border-dashed p-4 text-sm text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
      >
        <Plus className="size-4" />
        New space
      </button>
    </div>
  )
}
