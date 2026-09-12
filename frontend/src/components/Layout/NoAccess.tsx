import { Link } from "@tanstack/react-router"
import { Lock } from "lucide-react"

import { Button } from "@/components/ui/button"
import { EmptyState } from "./EmptyState"

export function NoAccess({ message }: { message?: string }) {
  return (
    <div className="p-6 md:p-10" data-testid="no-access">
      <EmptyState
        icon={Lock}
        title="You don't have access to this page"
        description={
          message ??
          "Ask the space owner to share it with you, or pick another space."
        }
        action={
          <Button asChild variant="outline">
            <Link to="/">Back to dashboard</Link>
          </Button>
        }
      />
    </div>
  )
}
