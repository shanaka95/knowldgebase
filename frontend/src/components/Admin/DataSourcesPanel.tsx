import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Copy } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import {
  AdminDataSourcesService,
  type DataSourceConfigPublic,
  type DataSourceConfigUpdate,
} from "@/client"
import { SourceIcon } from "@/components/Common/ChannelIcon"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"

/**
 * Where an administrator supplies the credentials a data source needs.
 *
 * Write-only, like the channels panel: a value that has been saved shows as
 * saved and never as itself, so this page cannot be used to read the client
 * secret back out of the deployment.
 */

const SOURCE_LABELS: Record<string, string> = { google_drive: "Google Drive" }

const FIELD_LABELS: Record<string, string> = {
  client_id: "OAuth client ID",
  client_secret: "OAuth client secret",
  api_key: "Picker API key",
}

const FIELD_HINTS: Record<string, string> = {
  client_id: "From the OAuth 2.0 Client ID you created (a Web application).",
  client_secret: "Its secret. Stored encrypted; it is never sent to a browser.",
  api_key:
    "Restrict it to the Picker API and to this site's referrer. The browser needs it, so it is public.",
}

export const dataSourceAdminKey = ["admin", "data-sources"] as const

export function DataSourcesPanel() {
  const { data, isPending } = useQuery({
    queryKey: dataSourceAdminKey,
    queryFn: async () => (await AdminDataSourcesService.readDataSources()).data,
  })

  if (isPending) return <Skeleton className="h-64 w-full" />

  return (
    <div className="flex flex-col gap-4">
      {(data?.data ?? []).map((source) => (
        <SourceForm key={source.source_type} source={source} />
      ))}
    </div>
  )
}

function SourceForm({ source }: { source: DataSourceConfigPublic }) {
  const queryClient = useQueryClient()
  const [values, setValues] = useState<Record<string, string>>({})
  const label = SOURCE_LABELS[source.source_type] ?? source.source_type

  const save = useMutation({
    mutationFn: async (body: DataSourceConfigUpdate) =>
      AdminDataSourcesService.updateDataSource({
        path: { source_type: source.source_type },
        body,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: dataSourceAdminKey })
      setValues({})
      toast.success(`${label} saved`)
    },
    onError: (error: { body?: { detail?: string } }) =>
      toast.error(error.body?.detail ?? `${label} could not be saved`),
  })

  return (
    <Card>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <SourceIcon
            channel={source.source_type}
            className="size-6 shrink-0"
          />
          <p className="font-medium">{label}</p>
          {source.configured ? (
            <Badge variant="secondary">Configured</Badge>
          ) : (
            <Badge variant="outline">Not configured</Badge>
          )}
          <div className="ml-auto flex items-center gap-2">
            <Label
              htmlFor={`${source.source_type}-enabled`}
              className="text-sm"
            >
              Offer to users
            </Label>
            <Switch
              id={`${source.source_type}-enabled`}
              checked={source.enabled}
              onCheckedChange={(enabled) => save.mutate({ enabled })}
              disabled={save.isPending}
            />
          </div>
        </div>

        <div className="flex min-w-0 flex-col gap-2">
          <Label>Redirect URI</Label>
          {/*
            Shown rather than documented: it has to match Google's
            registration exactly, and a trailing slash out of place fails with
            an error that says nothing about which end is wrong.
          */}
          <div className="flex min-w-0 items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-md bg-muted px-3 py-2 text-xs">
              {source.redirect_uri}
            </code>
            <Button
              variant="outline"
              size="icon"
              aria-label="Copy the redirect URI"
              onClick={() => {
                void navigator.clipboard
                  .writeText(source.redirect_uri)
                  .then(() => toast.success("Redirect URI copied"))
              }}
            >
              <Copy />
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Add this to the OAuth client's authorised redirect URIs in the
            Google Cloud console.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {source.required_fields.map((field) => {
            const isSet = source.present_fields.includes(field)
            return (
              <div key={field} className="flex min-w-0 flex-col gap-2">
                <Label htmlFor={`${source.source_type}-${field}`}>
                  {FIELD_LABELS[field] ?? field}
                </Label>
                <Input
                  id={`${source.source_type}-${field}`}
                  type="password"
                  autoComplete="off"
                  value={values[field] ?? ""}
                  onChange={(e) =>
                    setValues((v) => ({ ...v, [field]: e.target.value }))
                  }
                  placeholder={isSet ? "•••••••• (saved)" : "Not set"}
                />
                <p className="text-xs text-muted-foreground wrap-anywhere">
                  {FIELD_HINTS[field] ?? ""}
                </p>
              </div>
            )
          })}
        </div>

        <div>
          <Button
            onClick={() => save.mutate({ credentials: values })}
            disabled={save.isPending || Object.keys(values).length === 0}
            data-testid={`save-${source.source_type}`}
          >
            Save credentials
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
