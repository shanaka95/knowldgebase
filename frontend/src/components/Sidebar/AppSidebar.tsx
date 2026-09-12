import { FileUp, Home, Search, Share2, Sparkles, Users } from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarSeparator,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { NamespaceSwitcher } from "./NamespaceSwitcher"
import { type Item, NavMain } from "./NavMain"
import { SpaceTree } from "./SpaceTree"
import { User } from "./User"

const baseItems: Item[] = [
  { icon: Home, title: "Dashboard", path: "/" },
  { icon: Share2, title: "Shared with me", path: "/shared" },
  { icon: Sparkles, title: "Ask", path: "/ask" },
  { icon: Search, title: "Search", path: "/search" },
  { icon: FileUp, title: "Imports", path: "/imports" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()

  const items = currentUser?.is_superuser
    ? [...baseItems, { icon: Users, title: "Admin", path: "/admin" }]
    : baseItems

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="gap-3 px-3 pt-3 group-data-[collapsible=icon]:items-center group-data-[collapsible=icon]:px-0">
        <div className="px-1 group-data-[collapsible=icon]:px-0">
          <Logo variant="responsive" />
        </div>
        <NamespaceSwitcher />
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={items} />
        <SidebarSeparator className="mx-0 group-data-[collapsible=icon]:hidden" />
        <SpaceTree />
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarAppearance />
        </SidebarMenu>
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
