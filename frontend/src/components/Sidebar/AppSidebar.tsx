import {
  Bot,
  Database,
  FileUp,
  LayoutDashboard,
  Search,
  Share2,
  Sparkles,
  Users,
} from "lucide-react"

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
  // Not Home: "home" is one of the icons a space can choose, and the most
  // likely choice for a personal one, so the two were identical in the
  // collapsed rail.
  { icon: LayoutDashboard, title: "Dashboard", path: "/" },
  { icon: Share2, title: "Shared with me", path: "/shared" },
  { icon: Sparkles, title: "Ask", path: "/ask" },
  { icon: Search, title: "Search", path: "/search" },
  { icon: FileUp, title: "Imports", path: "/imports" },
  // Integrations, in the two directions they run: an agent is how you
  // reach the knowledge base, a data source is how documents reach it.
  { icon: Bot, title: "Agents", path: "/agents" },
  { icon: Database, title: "Data sources", path: "/data-sources" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()

  const items = currentUser?.is_superuser
    ? [...baseItems, { icon: Users, title: "Admin", path: "/admin" }]
    : baseItems

  return (
    <Sidebar collapsible="icon">
      {/*
        px-2 matches SidebarGroup below, so the space switcher, the logo and the
        navigation icons all sit on the same vertical line - collapsed or not.
        The header used to be px-3 with its own collapsed overrides, which put
        it four pixels out expanded and eight out collapsed.
      */}
      <SidebarHeader className="gap-4 px-2 pt-3 pb-4">
        <div className="px-1 group-data-[collapsible=icon]:flex group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
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
