import { useQuery } from "@tanstack/react-query"
import { KeyRound } from "lucide-react"

import type { ApiKeyPublic } from "@/client"
import { EmptyState } from "@/components/Layout/EmptyState"
import { PendingList } from "@/components/Pending/PendingList"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { relativeTime, shortDate } from "@/lib/format"
import { apiKeysQuery } from "@/queries/apiKeys"
import { CreateApiKeyDialog } from "./CreateApiKeyDialog"
import { RevokeApiKeyDialog } from "./RevokeApiKeyDialog"

function isExpired(k: ApiKeyPublic) {
  return Boolean(k.expires_at && new Date(k.expires_at).getTime() < Date.now())
}

export function ApiKeysTable() {
  const { data, isPending } = useQuery(apiKeysQuery())
  const keys = (data?.data ?? []).filter((k) => !k.revoked_at)

  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold">API keys</h2>
          <p className="text-sm text-muted-foreground">
            Personal keys let scripts and third-party apps read or write your
            pages via the REST API. Keys are shown only once when created.
          </p>
        </div>
        <CreateApiKeyDialog />
      </div>
      {isPending ? (
        <PendingList rows={3} />
      ) : keys.length === 0 ? (
        <EmptyState
          compact
          icon={KeyRound}
          title="No API keys yet"
          description="Create a key to connect an integration, then follow the examples in the Developer tab."
        />
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Name</TableHead>
                <TableHead>Key</TableHead>
                <TableHead>Scope</TableHead>
                <TableHead className="hidden md:table-cell">Created</TableHead>
                <TableHead className="hidden md:table-cell">Expires</TableHead>
                <TableHead className="hidden lg:table-cell">
                  Last used
                </TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {keys.map((k) => {
                const expired = isExpired(k)
                return (
                  <TableRow key={k.id} data-testid="api-key-row">
                    <TableCell className="font-medium">{k.name}</TableCell>
                    <TableCell>
                      <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                        {k.key_prefix}…
                      </code>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={k.scope === "write" ? "default" : "secondary"}
                      >
                        {k.scope === "write" ? "read & write" : "read"}
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden text-muted-foreground md:table-cell">
                      {shortDate(k.created_at)}
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      {k.expires_at ? (
                        <span
                          className={
                            expired
                              ? "text-destructive"
                              : "text-muted-foreground"
                          }
                        >
                          {expired ? "Expired " : ""}
                          {shortDate(k.expires_at)}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">Never</span>
                      )}
                    </TableCell>
                    <TableCell className="hidden text-muted-foreground lg:table-cell">
                      {k.last_used_at ? relativeTime(k.last_used_at) : "Never"}
                    </TableCell>
                    <TableCell className="text-right">
                      <RevokeApiKeyDialog apiKey={k} />
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

export default ApiKeysTable
