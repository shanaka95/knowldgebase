import {
  Bot,
  ChartColumn,
  Database,
  LayoutDashboard,
  Search,
  Share2,
  Sparkles,
  Upload,
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
import { CreditsMeter } from "./CreditsMeter"
import { NamespaceSwitcher } from "./NamespaceSwitcher"
import { type Item, NavMain } from "./NavMain"
import { SpaceTree } from "./SpaceTree"
import { User } from "./User"

/**
 * Ordered by what somebody opened the app to do, not by how the product grew.
 *
 * Asking is the point of the thing, so it leads. Then searching, then getting
 * documents in — those three are the daily loop. Where pages live comes next,
 * and the integrations and the meter last, because they are visited
 * occasionally and on purpose.
 */
const baseItems: Item[] = [
  { icon: Sparkles, title: "Ask", path: "/ask" },
  { icon: Search, title: "Search", path: "/search" },
  { icon: Upload, title: "Upload documents", path: "/capture" },

  // Not Home: "home" is one of the icons a space can choose, and the most
  // likely choice for a personal one, so the two were identical in the
  // collapsed rail.
  { icon: LayoutDashboard, title: "Dashboard", path: "/", startsGroup: true },
  { icon: Share2, title: "Shared with me", path: "/shared" },

  // Integrations, in the two directions they run: an agent is how you reach
  // the knowledge base, a data source is how documents reach it.
  { icon: Bot, title: "Agents", path: "/agents", startsGroup: true },
  { icon: Database, title: "Data sources", path: "/data-sources" },
  { icon: ChartColumn, title: "Usage", path: "/usage" },
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
        {/*
          Centred in both states. Collapsed, that puts the mark on the icon rail
          with the navigation below it; expanded, it sits centred over the space
          switcher rather than hugging the left edge.
        */}
        <div className="flex justify-center px-1 group-data-[collapsible=icon]:px-0">
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
        {/* Above the theme switch and the account: it is the one number in
            here that changes on its own. */}
        <CreditsMeter />
        <SidebarMenu>
          <SidebarAppearance />
        </SidebarMenu>
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
