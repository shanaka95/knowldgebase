import { Appearance } from "@/components/Common/Appearance"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { Breadcrumbs } from "./Breadcrumbs"
import { SearchButton } from "./SearchButton"

interface AppHeaderProps {
  onOpenSearch?: () => void
  actions?: React.ReactNode
}

export function AppHeader({ onOpenSearch, actions }: AppHeaderProps) {
  return (
    <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-2 border-b bg-background/95 px-3 backdrop-blur supports-[backdrop-filter]:bg-background/80 md:px-4">
      <SidebarTrigger className="-ml-1 text-muted-foreground" />
      <Separator orientation="vertical" className="mr-1 h-5!" />
      <div className="min-w-0 flex-1">
        <Breadcrumbs />
      </div>
      <div className="flex items-center gap-2">
        {actions}
        <SearchButton onOpen={onOpenSearch} />
        <Appearance />
      </div>
    </header>
  )
}
