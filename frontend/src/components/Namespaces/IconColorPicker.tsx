import { Check } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  NAMESPACE_COLOR_NAMES,
  NAMESPACE_COLORS,
  NAMESPACE_ICON_NAMES,
  NAMESPACE_ICONS,
  NamespaceIcon,
} from "./NamespaceIcon"

interface IconColorPickerProps {
  icon: string
  color: string
  onIconChange: (icon: string) => void
  onColorChange: (color: string) => void
}

export function IconColorPicker({
  icon,
  color,
  onIconChange,
  onColorChange,
}: IconColorPickerProps) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <NamespaceIcon icon={icon} color={color} size="lg" />
        <fieldset className="flex flex-wrap gap-1.5">
          <legend className="sr-only">Colour</legend>
          {NAMESPACE_COLOR_NAMES.map((name) => {
            const selected = name === color
            return (
              <button
                key={name}
                type="button"
                aria-pressed={selected}
                aria-label={name}
                onClick={() => onColorChange(name)}
                className={cn(
                  "flex size-6 items-center justify-center rounded-full ring-offset-background transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                  NAMESPACE_COLORS[name].swatch,
                  selected && "ring-2 ring-foreground/60 ring-offset-2",
                )}
              >
                {selected && <Check className="size-3.5 text-white" />}
              </button>
            )
          })}
        </fieldset>
      </div>
      <fieldset className="grid grid-cols-6 gap-1.5 sm:grid-cols-12">
        <legend className="sr-only">Icon</legend>
        {NAMESPACE_ICON_NAMES.map((name) => {
          const Icon = NAMESPACE_ICONS[name]
          const selected = name === icon
          return (
            <button
              key={name}
              type="button"
              aria-pressed={selected}
              aria-label={name}
              onClick={() => onIconChange(name)}
              className={cn(
                "flex size-9 items-center justify-center rounded-md border text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                selected && "border-primary bg-primary/10 text-primary",
              )}
            >
              <Icon className="size-4" />
            </button>
          )
        })}
      </fieldset>
    </div>
  )
}
