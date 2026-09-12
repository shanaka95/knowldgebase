import { Search } from "lucide-react"

import { Kbd, KbdGroup } from "@/components/ui/kbd"
import { cn } from "@/lib/utils"

interface SearchButtonProps {
  onOpen?: () => void
  className?: string
}

export function SearchButton({ onOpen, className }: SearchButtonProps) {
  return (
    <button
      type="button"
      onClick={onOpen}
      data-testid="search-button"
      className={cn(
        "group inline-flex h-9 items-center gap-2 rounded-md border bg-muted/40 px-3 text-sm text-muted-foreground shadow-xs transition-colors hover:bg-muted hover:text-foreground",
        "w-9 justify-center md:w-56 md:justify-start",
        className,
      )}
    >
      <Search className="size-4 shrink-0" />
      <span className="hidden flex-1 text-left md:inline">Search pages…</span>
      <KbdGroup className="hidden md:flex">
        <Kbd>⌘</Kbd>
        <Kbd>K</Kbd>
      </KbdGroup>
      <span className="sr-only">Search</span>
    </button>
  )
}
