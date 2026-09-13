import { Check, Monitor, Moon, Sun } from "lucide-react"
import { useEffect, useState } from "react"

import { type Theme, useTheme } from "@/components/theme-provider"
import { Label } from "@/components/ui/label"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { cn } from "@/lib/utils"

const themes: {
  value: Theme
  label: string
  icon: typeof Sun
  hint: string
}[] = [
  { value: "light", label: "Light", icon: Sun, hint: "Bright and clean" },
  { value: "dark", label: "Dark", icon: Moon, hint: "Easy on the eyes" },
  { value: "system", label: "System", icon: Monitor, hint: "Follows your OS" },
]

export const EDITOR_WIDTH_KEY = "kb:editor-width"
export type EditorWidth = "comfortable" | "wide"

export function readEditorWidth(): EditorWidth {
  try {
    return localStorage.getItem(EDITOR_WIDTH_KEY) === "wide"
      ? "wide"
      : "comfortable"
  } catch {
    return "comfortable"
  }
}

export function AppearanceSettings() {
  const { theme, setTheme } = useTheme()
  const [width, setWidth] = useState<EditorWidth>(readEditorWidth)

  useEffect(() => {
    try {
      localStorage.setItem(EDITOR_WIDTH_KEY, width)
    } catch {
      // ignore
    }
    document.documentElement.style.setProperty(
      "--kb-editor-max-width",
      width === "wide" ? "1200px" : "860px",
    )
  }, [width])

  return (
    <div className="flex max-w-2xl flex-col gap-8">
      <section className="flex flex-col gap-3">
        <div>
          <h3 className="text-base font-medium">Theme</h3>
          <p className="text-sm text-muted-foreground">
            Choose how the interface looks.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {themes.map((t) => {
            const active = theme === t.value
            return (
              <button
                type="button"
                key={t.value}
                onClick={() => setTheme(t.value)}
                data-testid={`${t.value}-mode`}
                className={cn(
                  "relative flex flex-col items-start gap-2 rounded-lg border p-4 text-left transition-colors hover:bg-accent",
                  active && "border-primary ring-2 ring-primary/30",
                )}
              >
                <t.icon className="size-5 text-muted-foreground" />
                <span className="font-medium">{t.label}</span>
                <span className="text-xs text-muted-foreground">{t.hint}</span>
                {active && (
                  <Check className="absolute right-3 top-3 size-4 text-primary" />
                )}
              </button>
            )
          })}
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <div>
          <h3 className="text-base font-medium">Editor width</h3>
          <p className="text-sm text-muted-foreground">
            Reading column width for pages.
          </p>
        </div>
        <ToggleGroup
          type="single"
          value={width}
          onValueChange={(v) => v && setWidth(v as EditorWidth)}
          variant="outline"
          className="w-fit"
        >
          <ToggleGroupItem value="comfortable" className="px-4">
            Comfortable
          </ToggleGroupItem>
          <ToggleGroupItem value="wide" className="px-4">
            Wide
          </ToggleGroupItem>
        </ToggleGroup>
        <Label className="sr-only">Editor width</Label>
      </section>
    </div>
  )
}

export default AppearanceSettings
