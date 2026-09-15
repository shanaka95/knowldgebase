import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import type { LucideIcon } from "lucide-react"

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

export type Item = {
  icon: LucideIcon
  title: string
  path: string
  /**
   * Start a new group above this item.
   *
   * The list is ordered by what people came to do, and a flat list of eight
   * hides that ordering: a hairline is what makes "ask and search" read as one
   * thing and "where my pages live" as another.
   */
  startsGroup?: boolean
}

interface NavMainProps {
  items: Item[]
}

export function NavMain({ items }: NavMainProps) {
  const { isMobile, setOpenMobile } = useSidebar()
  const router = useRouterState()
  const currentPath = router.location.pathname

  const handleMenuClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  return (
    <SidebarGroup>
      <SidebarGroupContent>
        <SidebarMenu className="gap-1.5">
          {items.map((item) => {
            const isActive = currentPath === item.path

            return (
              <SidebarMenuItem
                key={item.title}
                className={
                  item.startsGroup
                    ? "mt-2 border-sidebar-border border-t pt-2.5"
                    : undefined
                }
              >
                <SidebarMenuButton
                  tooltip={item.title}
                  isActive={isActive}
                  asChild
                >
                  <RouterLink to={item.path} onClick={handleMenuClick}>
                    <item.icon />
                    <span>{item.title}</span>
                  </RouterLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            )
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}
