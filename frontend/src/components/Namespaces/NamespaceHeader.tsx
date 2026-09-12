import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { Settings2, Share2 } from "lucide-react"

import type { NamespacePublic } from "@/client"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { canAdminNamespace } from "@/hooks/useNamespaces"
import { namespaceMembersQuery } from "@/queries/namespaces"
import { openDialog } from "@/stores/dialogs"
import { getInitials } from "@/utils"
import { NamespaceIcon } from "./NamespaceIcon"
import { RoleBadge } from "./RoleBadge"

export function NamespaceHeader({ namespace }: { namespace: NamespacePublic }) {
  const isAdmin = canAdminNamespace(namespace)
  const { data: members } = useQuery({
    ...namespaceMembersQuery(namespace.id),
    enabled: Boolean(namespace.my_role),
  })
  const people = members?.data ?? []

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex min-w-0 items-start gap-4">
        <NamespaceIcon
          icon={namespace.icon}
          color={namespace.color}
          size="lg"
        />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1
              className="truncate text-2xl font-semibold tracking-tight"
              data-testid="space-title"
            >
              {namespace.name}
            </h1>
            <RoleBadge role={namespace.my_role} />
          </div>
          {namespace.description && (
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
              {namespace.description}
            </p>
          )}
          <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
            <span>
              {namespace.document_count ?? 0} page
              {namespace.document_count === 1 ? "" : "s"}
            </span>
            {people.length > 0 && (
              <span className="flex items-center gap-1.5">
                <span className="flex -space-x-1.5">
                  {people.slice(0, 5).map((m) => (
                    <Avatar
                      key={m.user.id}
                      className="size-5 border border-background"
                    >
                      <AvatarFallback className="text-[9px]">
                        {getInitials(m.user.full_name || m.user.email)}
                      </AvatarFallback>
                    </Avatar>
                  ))}
                </span>
                {people.length} member{people.length === 1 ? "" : "s"}
              </span>
            )}
          </div>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {isAdmin && (
          <Button
            variant="outline"
            onClick={() =>
              openDialog({
                kind: "share",
                target: {
                  type: "namespace",
                  id: namespace.id,
                  slug: namespace.slug,
                  name: namespace.name,
                },
              })
            }
            data-testid="space-share"
          >
            <Share2 />
            Share
          </Button>
        )}
        {isAdmin && (
          <Button
            variant="outline"
            size="icon"
            asChild
            aria-label="Space settings"
          >
            <Link
              to="/s/$namespaceSlug/settings"
              params={{ namespaceSlug: namespace.slug }}
              search={{ tab: "general" }}
            >
              <Settings2 />
            </Link>
          </Button>
        )}
      </div>
    </div>
  )
}
