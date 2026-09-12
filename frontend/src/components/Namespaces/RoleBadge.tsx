import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

const LABELS: Record<string, string> = {
  admin: "Admin",
  editor: "Editor",
  viewer: "Viewer",
  owner: "Owner",
}

export function RoleBadge({
  role,
  isOwner,
  className,
}: {
  role?: string | null
  isOwner?: boolean
  className?: string
}) {
  const key = isOwner ? "owner" : (role ?? "")
  if (!LABELS[key]) return null
  return (
    <Badge
      variant={key === "owner" || key === "admin" ? "default" : "secondary"}
      className={cn(
        "px-1.5 py-0 text-[10px] uppercase tracking-wide",
        className,
      )}
    >
      {LABELS[key]}
    </Badge>
  )
}
