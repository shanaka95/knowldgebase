import { RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"

export function NewVersionChip({
  version,
  onRefresh,
}: {
  version: number
  onRefresh: () => void
}) {
  return (
    <Button
      size="sm"
      variant="outline"
      className="h-7 rounded-full border-info/40 bg-info/10 text-xs text-info hover:bg-info/20"
      onClick={onRefresh}
      data-testid="new-version-chip"
    >
      <RefreshCw className="size-3" />
      New version (v{version}) available · Refresh
    </Button>
  )
}

export default NewVersionChip
