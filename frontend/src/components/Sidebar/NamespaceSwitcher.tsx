import { Link, useNavigate } from "@tanstack/react-router"
import {
  Check,
  ChevronsUpDown,
  FolderKanban,
  Plus,
  Settings2,
} from "lucide-react"

import { NamespaceIcon } from "@/components/Namespaces/NamespaceIcon"
import { RoleBadge } from "@/components/Namespaces/RoleBadge"
import { SharedSpaceBadge } from "@/components/Namespaces/SharedSpaceBadge"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  useSidebar,
} from "@/components/ui/sidebar"
import {
  rememberNamespaceSlug,
  useActiveNamespace,
} from "@/hooks/useNamespaces"
import { openDialog } from "@/stores/dialogs"

export function NamespaceSwitcher() {
  const { isMobile, setOpenMobile } = useSidebar()
  const navigate = useNavigate()
  const { active, namespaces, isPending } = useActiveNamespace()

  if (isPending) {
    return (
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuSkeleton showIcon />
        </SidebarMenuItem>
      </SidebarMenu>
    )
  }

  const select = (slug: string) => {
    rememberNamespaceSlug(slug)
    navigate({ to: "/s/$namespaceSlug", params: { namespaceSlug: slug } })
    if (isMobile) setOpenMobile(false)
  }

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              /*
               * Collapsed, this button is a 32px square with no padding, so its
               * contents would otherwise sit hard against the left edge while
               * every navigation icon below is centred by padding. Centring
               * here, and shrinking the tile a little, puts it on the same axis
               * at the same visual weight.
               */
              className="group-data-[collapsible=icon]:justify-center data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
              data-testid="namespace-switcher"
            >
              {active ? (
                <NamespaceIcon
                  icon={active.icon}
                  color={active.color}
                  className="group-data-[collapsible=icon]:size-7"
                />
              ) : (
                <span className="flex aspect-square size-8 items-center justify-center rounded-md bg-muted text-muted-foreground group-data-[collapsible=icon]:size-7">
                  <FolderKanban className="size-4" />
                </span>
              )}
              {/*
                Hidden outright when collapsed rather than merely clipped: they
                are flex siblings, so leaving them in the layout squeezes the
                tile down to a sliver inside the 32px button.
              */}
              <div className="grid min-w-0 flex-1 text-left text-sm leading-tight group-data-[collapsible=icon]:hidden">
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate font-medium">
                    {active?.name ?? "No spaces yet"}
                  </span>
                  <SharedSpaceBadge shared={active?.shared_with_you} />
                </span>
                <span className="truncate text-xs text-muted-foreground">
                  {active
                    ? `${active.document_count ?? 0} page${
                        active.document_count === 1 ? "" : "s"
                      } · ${active.my_role ?? "viewer"}`
                    : "Create your first space"}
                </span>
              </div>
              <ChevronsUpDown className="ml-auto size-4 text-muted-foreground group-data-[collapsible=icon]:hidden" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-dropdown-menu-trigger-width) min-w-64 rounded-lg"
            side={isMobile ? "bottom" : "right"}
            align="start"
            sideOffset={4}
          >
            <DropdownMenuLabel className="text-xs text-muted-foreground">
              Spaces
            </DropdownMenuLabel>
            {namespaces.map((ns) => (
              <DropdownMenuItem
                key={ns.id}
                className="gap-2 p-2"
                onClick={() => select(ns.slug)}
                data-testid={`namespace-option-${ns.slug}`}
              >
                <NamespaceIcon icon={ns.icon} color={ns.color} size="sm" />
                <span className="flex-1 truncate">{ns.name}</span>
                <SharedSpaceBadge shared={ns.shared_with_you} />
                <RoleBadge role={ns.my_role} />
                {ns.id === active?.id && (
                  <Check className="size-4 text-primary" />
                )}
              </DropdownMenuItem>
            ))}
            {namespaces.length > 0 && <DropdownMenuSeparator />}
            <DropdownMenuItem
              className="gap-2 p-2"
              onClick={() => openDialog({ kind: "createNamespace" })}
              data-testid="create-namespace"
            >
              <div className="flex size-6 items-center justify-center rounded-md border bg-background">
                <Plus className="size-4" />
              </div>
              <div className="font-medium">Create space…</div>
            </DropdownMenuItem>
            {active && (
              <DropdownMenuItem asChild className="gap-2 p-2">
                <Link
                  to="/s/$namespaceSlug/settings"
                  params={{ namespaceSlug: active.slug }}
                  search={{ tab: "general" }}
                >
                  <div className="flex size-6 items-center justify-center rounded-md border bg-background">
                    <Settings2 className="size-4" />
                  </div>
                  <div className="font-medium">Space settings</div>
                </Link>
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
