import {
  BookOpen,
  Briefcase,
  Code2,
  Folder,
  Globe,
  Heart,
  Home,
  Layers,
  Lightbulb,
  type LucideIcon,
  Rocket,
  Star,
  Users,
} from "lucide-react"

import { cn } from "@/lib/utils"

export const NAMESPACE_ICONS: Record<string, LucideIcon> = {
  folder: Folder,
  briefcase: Briefcase,
  home: Home,
  book: BookOpen,
  rocket: Rocket,
  users: Users,
  code: Code2,
  lightbulb: Lightbulb,
  heart: Heart,
  star: Star,
  globe: Globe,
  layers: Layers,
}

export const NAMESPACE_ICON_NAMES = Object.keys(NAMESPACE_ICONS)

export const NAMESPACE_COLORS: Record<
  string,
  { swatch: string; surface: string; text: string }
> = {
  indigo: {
    swatch: "bg-indigo-500",
    surface: "bg-indigo-500/15",
    text: "text-indigo-600 dark:text-indigo-300",
  },
  blue: {
    swatch: "bg-sky-500",
    surface: "bg-sky-500/15",
    text: "text-sky-600 dark:text-sky-300",
  },
  emerald: {
    swatch: "bg-emerald-500",
    surface: "bg-emerald-500/15",
    text: "text-emerald-600 dark:text-emerald-300",
  },
  amber: {
    swatch: "bg-amber-500",
    surface: "bg-amber-500/15",
    text: "text-amber-600 dark:text-amber-300",
  },
  rose: {
    swatch: "bg-rose-500",
    surface: "bg-rose-500/15",
    text: "text-rose-600 dark:text-rose-300",
  },
  violet: {
    swatch: "bg-violet-500",
    surface: "bg-violet-500/15",
    text: "text-violet-600 dark:text-violet-300",
  },
  cyan: {
    swatch: "bg-cyan-500",
    surface: "bg-cyan-500/15",
    text: "text-cyan-600 dark:text-cyan-300",
  },
  slate: {
    swatch: "bg-slate-500",
    surface: "bg-slate-500/15",
    text: "text-slate-600 dark:text-slate-300",
  },
}

export const NAMESPACE_COLOR_NAMES = Object.keys(NAMESPACE_COLORS)

export function resolveIcon(name?: string | null): LucideIcon {
  return NAMESPACE_ICONS[name ?? ""] ?? Folder
}

export function resolveColor(name?: string | null) {
  return NAMESPACE_COLORS[name ?? ""] ?? NAMESPACE_COLORS.indigo
}

interface NamespaceIconProps {
  icon?: string | null
  color?: string | null
  size?: "xs" | "sm" | "md" | "lg"
  className?: string
}

const sizes = {
  xs: { box: "size-5 rounded", icon: "size-3" },
  sm: { box: "size-6 rounded-md", icon: "size-3.5" },
  md: { box: "size-8 rounded-md", icon: "size-4" },
  lg: { box: "size-12 rounded-lg", icon: "size-6" },
}

/** Coloured square with the space's icon; used everywhere a space is referenced. */
export function NamespaceIcon({
  icon,
  color,
  size = "md",
  className,
}: NamespaceIconProps) {
  const Icon = resolveIcon(icon)
  const palette = resolveColor(color)
  const s = sizes[size]
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center",
        s.box,
        palette.surface,
        palette.text,
        className,
      )}
      aria-hidden="true"
    >
      <Icon className={s.icon} />
    </span>
  )
}
