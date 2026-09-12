import { Trash2 } from "lucide-react"

import type { NamespacePublic } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { openDialog } from "@/stores/dialogs"

export function NamespaceDangerZone({
  namespace,
}: {
  namespace: NamespacePublic
}) {
  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle className="text-destructive">Danger zone</CardTitle>
        <CardDescription>
          Deleting a space removes every folder, page, attachment and share in
          it. There is no undo.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button
          variant="destructive"
          onClick={() =>
            openDialog({
              kind: "deleteNamespace",
              target: {
                type: "namespace",
                id: namespace.id,
                slug: namespace.slug,
                name: namespace.name,
              },
            })
          }
          data-testid="space-delete"
        >
          <Trash2 />
          Delete this space
        </Button>
      </CardContent>
    </Card>
  )
}
