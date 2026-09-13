import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import {
  Database,
  ExternalLink,
  FilePlus2,
  Loader2,
  Unplug,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"

import { DataSourcesService, type ImportJobsPublic } from "@/client"
import { SourceIcon } from "@/components/Common/ChannelIcon"
import { DestinationFields } from "@/components/Imports/DestinationFields"
import { PageContainer, PageHeader } from "@/components/Layout/PageContainer"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { type PickedFile, pickFromGoogleDrive } from "@/hooks/useGooglePicker"
import { canEditNamespace, useNamespaces } from "@/hooks/useNamespaces"
import { importKeys } from "@/queries/imports"

export const Route = createFileRoute("/_layout/data-sources")({
  component: DataSourcesPage,
  staticData: { crumb: "Data sources" },
  head: () => ({ meta: [{ title: "Data sources - PlusGPT" }] }),
  validateSearch: (search: Record<string, unknown>) => ({
    connected:
      typeof search.connected === "string" ? search.connected : undefined,
    reason: typeof search.reason === "string" ? search.reason : undefined,
  }),
})

const SOURCE_LABELS: Record<string, string> = {
  google_drive: "Google Drive",
}

const dataSourcesQuery = {
  queryKey: ["data-sources"] as const,
  queryFn: async () => (await DataSourcesService.readDataSources()).data,
}

function DataSourcesPage() {
  const { connected, reason } = Route.useSearch()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data, isPending } = useQuery(dataSourcesQuery)
  const [picked, setPicked] = useState<PickedFile[] | null>(null)

  // The OAuth round trip comes back as a redirect, so the outcome arrives in
  // the URL rather than from a mutation. Report it once, then clear it so a
  // refresh does not repeat the message.
  useEffect(() => {
    if (!connected) return
    if (connected === "1") {
      toast.success("Google Drive connected")
      void queryClient.invalidateQueries({ queryKey: ["data-sources"] })
    } else {
      toast.error(explainFailure(reason))
    }
    void navigate({
      to: "/data-sources",
      search: { connected: undefined, reason: undefined },
      replace: true,
    })
  }, [connected, reason, navigate, queryClient])

  const sources = data?.data ?? []

  return (
    <PageContainer className="flex flex-col gap-6">
      <PageHeader
        title="Data sources"
        description="Places your documents come from, so you do not have to upload them by hand."
      />

      {isPending ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Skeleton className="h-32 w-full" />
        </div>
      ) : sources.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Database />
            </EmptyMedia>
            <EmptyTitle>Nothing to connect yet</EmptyTitle>
            <EmptyDescription>
              An administrator has not switched on any data sources for this
              deployment. Until then, use Capture to add files yourself.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {sources.map((source) => (
            <SourceCard
              key={source.source_type}
              source={source}
              onPicked={setPicked}
            />
          ))}
        </div>
      )}

      <ImportPickedDialog picked={picked} onClose={() => setPicked(null)} />
    </PageContainer>
  )
}

function explainFailure(reason: string | undefined): string {
  if (!reason) return "Google Drive was not connected."
  if (reason === "access_denied")
    return "You did not grant access, so nothing changed."
  if (reason === "drive_access_not_granted") {
    return "PlusGPT needs permission to open the files you pick. Connect again and leave that box ticked."
  }
  if (reason === "missing_code")
    return "Google sent us back without an answer. Try again."
  return reason
}

function SourceCard({
  source,
  onPicked,
}: {
  source: {
    source_type: string
    available: boolean
    connected: boolean
    account_email?: string | null
  }
  onPicked: (files: PickedFile[]) => void
}) {
  const queryClient = useQueryClient()
  const [opening, setOpening] = useState(false)
  const label = SOURCE_LABELS[source.source_type] ?? source.source_type

  const connect = useMutation({
    mutationFn: async () =>
      (await DataSourcesService.authorizeGoogleDrive()).data,
    // The reply is the consent URL rather than a result: leaving the app is
    // the point, so the browser is sent there directly.
    onSuccess: (body) => {
      window.location.href = body.message
    },
    onError: (error: { body?: { detail?: string } }) =>
      toast.error(error.body?.detail ?? "Google Drive could not be connected"),
  })

  const disconnect = useMutation({
    mutationFn: async () => DataSourcesService.disconnectGoogleDrive(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["data-sources"] })
      toast.success(`${label} disconnected`)
    },
    onError: () => toast.error(`${label} could not be disconnected`),
  })

  async function choose() {
    setOpening(true)
    try {
      const files = await pickFromGoogleDrive()
      if (files.length > 0) onPicked(files)
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "The file chooser did not open",
      )
    } finally {
      setOpening(false)
    }
  }

  return (
    <Card className="h-full">
      <CardContent className="flex flex-col gap-4">
        <div className="flex items-start gap-3">
          <SourceIcon
            channel={source.source_type}
            className="size-8 shrink-0"
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-medium">{label}</p>
              {source.connected ? (
                <Badge variant="secondary">Connected</Badge>
              ) : !source.available ? (
                <Badge variant="outline">Not available</Badge>
              ) : null}
            </div>
            <p className="mt-1 text-sm text-muted-foreground wrap-anywhere">
              {source.connected
                ? (source.account_email ??
                  "Choose files and they become searchable pages.")
                : source.available
                  ? "Pick files in Google's own chooser. PlusGPT sees only what you pick — never the rest of your Drive."
                  : "An administrator has not switched this on yet."}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {source.connected ? (
            <>
              <Button onClick={choose} disabled={opening}>
                {opening ? <Loader2 className="animate-spin" /> : <FilePlus2 />}
                Choose files
              </Button>
              <Button
                variant="outline"
                onClick={() => disconnect.mutate()}
                disabled={disconnect.isPending}
              >
                <Unplug />
                Disconnect
              </Button>
            </>
          ) : (
            <Button
              onClick={() => connect.mutate()}
              disabled={!source.available || connect.isPending}
              data-testid={`connect-${source.source_type}`}
            >
              <ExternalLink />
              Connect
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function ImportPickedDialog({
  picked,
  onClose,
}: {
  picked: PickedFile[] | null
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const { data: namespaces } = useNamespaces()
  const editable = useMemo(
    () => (namespaces?.data ?? []).filter(canEditNamespace),
    [namespaces],
  )
  const [spaceId, setSpaceId] = useState("")
  const [folderId, setFolderId] = useState<string | null>(null)

  useEffect(() => {
    if (picked && !spaceId && editable[0]) setSpaceId(editable[0].id)
  }, [picked, spaceId, editable])

  const startImport = useMutation({
    mutationFn: async (): Promise<ImportJobsPublic> =>
      (
        await DataSourcesService.importFromGoogleDrive({
          body: {
            files: picked ?? [],
            namespace_id: spaceId,
            folder_id: folderId,
          },
        })
      ).data,
    onSuccess: (body) => {
      void queryClient.invalidateQueries({ queryKey: importKeys.all })
      toast.success(
        body.count === 1
          ? "One file is being turned into a page"
          : `${body.count} files are being turned into pages`,
      )
      onClose()
    },
    onError: (error: { body?: { detail?: string } }) =>
      toast.error(error.body?.detail ?? "Those files could not be imported"),
  })

  const count = picked?.length ?? 0

  return (
    <Dialog open={picked !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {count === 1 ? "Import one file" : `Import ${count} files`}
          </DialogTitle>
          <DialogDescription>
            Each becomes its own page, with the original kept attached to it.
          </DialogDescription>
        </DialogHeader>

        <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto text-sm">
          {(picked ?? []).map((file) => (
            <li
              key={file.file_id}
              className="flex min-w-0 items-center gap-2 text-muted-foreground"
            >
              <FilePlus2 className="size-3.5 shrink-0" />
              <span className="min-w-0 truncate">{file.name}</span>
            </li>
          ))}
        </ul>

        <DestinationFields
          spaces={editable}
          spaceId={spaceId}
          onSpaceChange={setSpaceId}
          folderId={folderId}
          onFolderChange={setFolderId}
          disabled={startImport.isPending}
          idPrefix="drive-import"
        />

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => startImport.mutate()}
            disabled={!spaceId || startImport.isPending}
            data-testid="drive-import-start"
          >
            {startImport.isPending && <Loader2 className="animate-spin" />}
            Import
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
