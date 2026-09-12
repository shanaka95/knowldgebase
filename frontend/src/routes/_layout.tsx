import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"

import { AppHeader } from "@/components/Layout/AppHeader"
import { RouteErrorComponent } from "@/components/Layout/RouteErrorComponent"
import { CommandPalette } from "@/components/Search/CommandPalette"
import { GlobalDialogs } from "@/components/Sharing/GlobalDialogs"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { isLoggedIn } from "@/hooks/useAuth"
import { useSearchDialogStore } from "@/stores/searchDialog"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
  errorComponent: RouteErrorComponent,
})

function Layout() {
  const openSearch = useSearchDialogStore((s) => s.open)

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="min-w-0">
        <AppHeader onOpenSearch={openSearch} />
        <main className="flex min-h-0 flex-1 flex-col">
          <Outlet />
        </main>
      </SidebarInset>
      <CommandPalette />
      <GlobalDialogs />
    </SidebarProvider>
  )
}
