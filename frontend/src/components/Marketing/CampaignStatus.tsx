import { useQuery } from "@tanstack/react-query"
import {
  ArrowLeft,
  CircleAlert,
  CircleCheck,
  Clock,
  MinusCircle,
} from "lucide-react"

import type { DeliveryStatus } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { relativeTime } from "@/lib/format"
import {
  campaignQuery,
  deliveriesQuery,
  useCancelCampaign,
} from "@/queries/adminMarketing"

const ICON: Record<DeliveryStatus, typeof Clock> = {
  pending: Clock,
  sent: CircleCheck,
  failed: CircleAlert,
  skipped: MinusCircle,
}

const TONE: Record<DeliveryStatus, string> = {
  pending: "text-muted-foreground",
  sent: "text-emerald-600 dark:text-emerald-400",
  failed: "text-destructive",
  skipped: "text-muted-foreground",
}

/**
 * What actually happened, address by address.
 *
 * Polling stops the moment the campaign does, so a finished one left open in a
 * tab costs nothing. At one message a second a real campaign takes minutes,
 * which is exactly long enough that somebody will want to watch it.
 */
export function CampaignStatus({
  campaignId,
  onBack,
}: {
  campaignId: string
  onBack: () => void
}) {
  const campaign = useQuery(campaignQuery(campaignId, true))
  const live = campaign.data?.status === "sending"
  const deliveries = useQuery(deliveriesQuery(campaignId, live))
  const cancel = useCancelCampaign()

  const rows = deliveries.data?.data ?? []
  const done =
    (campaign.data?.sent_count ?? 0) + (campaign.data?.failed_count ?? 0)
  const total = campaign.data?.total ?? 0
  const remaining = Math.max(0, total - done)

  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="marketing-status">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onBack}
          aria-label="Back"
        >
          <ArrowLeft />
        </Button>
        <div className="min-w-0 flex-1">
          <p className="wrap-anywhere font-medium">
            {campaign.data?.subject ?? "Campaign"}
          </p>
          <p className="wrap-anywhere text-muted-foreground text-sm">
            From {campaign.data?.from_email}
          </p>
        </div>
        {campaign.data && (
          <Badge variant={live ? "default" : "outline"} className="shrink-0">
            {campaign.data.status}
          </Badge>
        )}
        {live && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => cancel.mutate(campaignId)}
            data-testid="marketing-cancel"
          >
            Stop sending
          </Button>
        )}
      </div>

      {campaign.isPending ? (
        <Skeleton className="h-16 w-full" />
      ) : (
        <div className="flex min-w-0 flex-col gap-2">
          <Progress value={total ? (done / total) * 100 : 0} />
          <p
            className="text-muted-foreground text-sm tabular-nums"
            data-testid="marketing-progress"
          >
            {campaign.data?.sent_count ?? 0} sent,{" "}
            {campaign.data?.failed_count ?? 0} failed, {remaining} to go.
            {live && " About one a second, so this takes a few minutes."}
          </p>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Address</TableHead>
              <TableHead className="w-28">Status</TableHead>
              <TableHead className="hidden w-32 sm:table-cell">When</TableHead>
              <TableHead className="hidden md:table-cell">Detail</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={4}
                  className="text-muted-foreground text-sm"
                >
                  Nothing queued for this campaign.
                </TableCell>
              </TableRow>
            )}
            {rows.map((row) => {
              const Icon = ICON[row.status]
              return (
                <TableRow key={row.id} data-testid="marketing-delivery-row">
                  <TableCell className="min-w-0">
                    <span className="wrap-anywhere">{row.to_email}</span>
                  </TableCell>
                  <TableCell>
                    <span
                      className={`flex items-center gap-1.5 text-sm ${TONE[row.status]}`}
                    >
                      <Icon className="size-4 shrink-0" />
                      {row.status}
                    </span>
                  </TableCell>
                  <TableCell className="hidden whitespace-nowrap text-muted-foreground text-sm sm:table-cell">
                    {row.sent_at
                      ? relativeTime(row.sent_at)
                      : relativeTime(row.send_after)}
                  </TableCell>
                  <TableCell className="hidden min-w-0 text-muted-foreground text-sm md:table-cell">
                    <span className="wrap-anywhere">{row.error ?? ""}</span>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
