import { forwardRef, useEffect, useImperativeHandle, useState } from "react"

import { cn } from "@/lib/utils"
import type { SlashItem } from "./items"

export interface SlashMenuProps {
  items: SlashItem[]
  command: (item: SlashItem) => void
}

export interface SlashMenuHandle {
  onKeyDown: (event: KeyboardEvent) => boolean
}

const GROUP_ORDER: SlashItem["group"][] = ["Basic", "Advanced", "Panels"]

export const SlashMenu = forwardRef<SlashMenuHandle, SlashMenuProps>(
  ({ items, command }, ref) => {
    const [selected, setSelected] = useState(0)

    useEffect(() => setSelected(0), [])

    useEffect(() => {
      const el = document.querySelector<HTMLElement>(
        `[data-slash-index="${selected}"]`,
      )
      el?.scrollIntoView({ block: "nearest" })
    }, [selected])

    useImperativeHandle(ref, () => ({
      onKeyDown: (event) => {
        if (event.key === "ArrowUp") {
          setSelected((s) => (s + items.length - 1) % Math.max(items.length, 1))
          return true
        }
        if (event.key === "ArrowDown") {
          setSelected((s) => (s + 1) % Math.max(items.length, 1))
          return true
        }
        if (event.key === "Enter" || event.key === "Tab") {
          const item = items[selected]
          if (item) command(item)
          return true
        }
        return false
      },
    }))

    if (items.length === 0) {
      return (
        <div className="w-72 rounded-lg border bg-popover p-3 text-sm text-muted-foreground shadow-md">
          No matching blocks
        </div>
      )
    }

    let index = -1
    return (
      <div
        className="max-h-80 w-72 overflow-y-auto rounded-lg border bg-popover p-1 text-popover-foreground shadow-md"
        role="listbox"
        data-testid="slash-menu"
      >
        {GROUP_ORDER.map((group) => {
          const groupItems = items.filter((i) => i.group === group)
          if (groupItems.length === 0) return null
          return (
            <div key={group} className="py-1">
              <div className="px-2 pb-1 pt-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                {group}
              </div>
              {groupItems.map((item) => {
                index += 1
                const i = index
                const isActive = i === selected
                return (
                  <button
                    type="button"
                    key={item.title}
                    role="option"
                    aria-selected={isActive}
                    data-slash-index={i}
                    onMouseEnter={() => setSelected(i)}
                    onMouseDown={(e) => {
                      e.preventDefault()
                      command(item)
                    }}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left text-sm outline-none",
                      isActive && "bg-accent text-accent-foreground",
                    )}
                  >
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-md border bg-background">
                      <item.icon className="size-4" />
                    </span>
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate font-medium">{item.title}</span>
                      <span className="truncate text-xs text-muted-foreground">
                        {item.description}
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>
          )
        })}
      </div>
    )
  },
)
SlashMenu.displayName = "SlashMenu"
