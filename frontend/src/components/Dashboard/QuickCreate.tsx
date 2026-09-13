import { ChevronDown, FilePlus2, FileUp, FolderPlus } from "lucide-react"

import { NamespaceIcon } from "@/components/Namespaces/NamespaceIcon"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useCreateDocument } from "@/hooks/useKbMutations"
import { canEditNamespace, useActiveNamespace } from "@/hooks/useNamespaces"
import { openDialog } from "@/stores/dialogs"

export function QuickCreate() {
  const { active, namespaces } = useActiveNamespace()
  const createDocument = useCreateDocument()
  const editable = namespaces.filter(canEditNamespace)

  return (
    <div className="flex gap-2">
      {editable.length > 0 ? (
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild>
            <Button
              disabled={createDocument.isPending}
              data-testid="quick-new-page"
            >
              <FilePlus2 />
              New page
              <ChevronDown className="opacity-70" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel className="text-xs text-muted-foreground">
              Create in space
            </DropdownMenuLabel>
            {editable.map((ns) => (
              <DropdownMenuItem
                key={ns.id}
                onClick={() =>
                  createDocument.mutate({
                    namespaceId: ns.id,
                    namespaceSlug: ns.slug,
                    folderId: null,
                  })
                }
                data-testid={`quick-new-page-${ns.slug}`}
              >
                <NamespaceIcon icon={ns.icon} color={ns.color} size="xs" />
                <span className="flex-1 truncate">{ns.name}</span>
                {ns.id === active?.id && (
                  <span className="text-xs text-muted-foreground">current</span>
                )}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() =>
                openDialog({
                  kind: "import",
                  namespaceId: active?.id ?? null,
                  namespaceSlug: active?.slug ?? null,
                  folderId: null,
                })
              }
              data-testid="quick-import"
            >
              <FileUp className="size-4" />
              Add a document…
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => openDialog({ kind: "createNamespace" })}
            >
              <FolderPlus className="size-4" />
              New space…
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        <Button
          onClick={() => openDialog({ kind: "createNamespace" })}
          data-testid="quick-new-space"
        >
          <FolderPlus />
          New space
        </Button>
      )}
    </div>
  )
}
