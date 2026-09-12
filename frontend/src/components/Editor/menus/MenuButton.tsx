import type { LucideIcon } from "lucide-react"

import { Toggle } from "@/components/ui/toggle"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

interface MenuButtonProps {
  icon: LucideIcon
  label: string
  shortcut?: string
  active?: boolean
  disabled?: boolean
  onClick: () => void
  className?: string
  destructive?: boolean
}

export function MenuButton({
  icon: Icon,
  label,
  shortcut,
  active = false,
  disabled = false,
  onClick,
  className,
  destructive = false,
}: MenuButtonProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Toggle
          size="sm"
          pressed={active}
          disabled={disabled}
          aria-label={label}
          onMouseDown={(e) => e.preventDefault()}
          onPressedChange={() => onClick()}
          className={cn(
            "size-8 p-0 data-[state=on]:bg-accent data-[state=on]:text-accent-foreground",
            destructive && "hover:text-destructive",
            className,
          )}
        >
          <Icon className="size-4" />
        </Toggle>
      </TooltipTrigger>
      <TooltipContent side="top" className="flex items-center gap-2">
        {label}
        {shortcut && (
          <kbd className="rounded bg-background/20 px-1 font-mono text-[10px]">
            {shortcut}
          </kbd>
        )}
      </TooltipContent>
    </Tooltip>
  )
}

export function MenuDivider() {
  return <span className="mx-0.5 h-5 w-px bg-border" aria-hidden />
}

export const menuSurface =
  "flex items-center gap-0.5 rounded-lg border bg-popover p-1 text-popover-foreground shadow-md"
