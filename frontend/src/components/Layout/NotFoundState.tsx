import { Link } from "@tanstack/react-router"
import { FileQuestion } from "lucide-react"

import { Button } from "@/components/ui/button"
import { EmptyState } from "./EmptyState"

export function NotFoundState({
  title = "Not found",
  description = "This page may have been moved or deleted.",
}: {
  title?: string
  description?: string
}) {
  return (
    <div className="p-6 md:p-10" data-testid="not-found-state">
      <EmptyState
        icon={FileQuestion}
        title={title}
        description={description}
        action={
          <Button asChild variant="outline">
            <Link to="/">Back to dashboard</Link>
          </Button>
        }
      />
    </div>
  )
}
