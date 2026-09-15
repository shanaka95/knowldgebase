import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { AdminCreditsService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { shortDate } from "@/lib/format"
import { queryKeys } from "@/lib/queryKeys"

/**
 * Topping one account up, and seeing where its month has gone.
 *
 * Only the one-off grants live here. The *allowance* is a limit like any
 * other, so it is set on the Groups screen or as an override on this account —
 * that is where a permanent change belongs, and the copy below says so rather
 * than leaving somebody to grant 1000 credits every month by hand.
 */

function credits(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(
    value,
  )
}

export function CreditsDialog({
  userId,
  name,
  open,
  onOpenChange,
}: {
  userId: string
  name: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [amount, setAmount] = useState("")
  const [reason, setReason] = useState("")
  const [days, setDays] = useState("")

  const balance = useQuery({
    queryKey: ["admin", "credits", userId],
    queryFn: async () =>
      (await AdminCreditsService.readBalance({ path: { user_id: userId } }))
        .data,
    enabled: open,
  })
  const grants = useQuery({
    queryKey: queryKeys.usage.grants(userId),
    queryFn: async () =>
      (await AdminCreditsService.readGrants({ path: { user_id: userId } }))
        .data,
    enabled: open,
  })

  const refresh = () => {
    void queryClient.invalidateQueries({
      queryKey: ["admin", "credits", userId],
    })
    void queryClient.invalidateQueries({
      queryKey: queryKeys.usage.grants(userId),
    })
  }

  const give = useMutation({
    mutationFn: async () =>
      AdminCreditsService.createGrant({
        path: { user_id: userId },
        body: {
          credits: Number(amount),
          reason,
          days: days ? Number(days) : null,
        },
      }),
    onSuccess: () => {
      toast.success(`${credits(Number(amount))} credits added`)
      setAmount("")
      setReason("")
      setDays("")
      refresh()
    },
    onError: (error: Error) =>
      toast.error(error.message || "The credits could not be added"),
  })

  const revoke = useMutation({
    mutationFn: async (grantId: string) =>
      AdminCreditsService.deleteGrant({
        path: { user_id: userId, grant_id: grantId },
      }),
    onSuccess: () => {
      toast.success("Grant removed")
      refresh()
    },
    onError: (error: Error) =>
      toast.error(error.message || "The grant could not be removed"),
  })

  const total = balance.data ? balance.data.allowance + balance.data.granted : 0
  // Filled by what is left, matching the card somebody else sees on their own
  // usage page - two screens showing the same number the same way round.
  const leftPercent =
    balance.data && total > 0
      ? Math.max(0, Math.min(100, (balance.data.remaining / total) * 100))
      : 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg" data-testid="credits-dialog">
        <DialogHeader>
          <DialogTitle>Credits for {name}</DialogTitle>
          <DialogDescription>
            A grant is a one-off top-up that ends when the month does. To change
            what this account gets <em>every</em> month, set its allowance on
            the Groups tab or as an override.
          </DialogDescription>
        </DialogHeader>

        <div className="flex min-w-0 flex-col gap-4">
          {balance.isPending ? (
            <Skeleton className="h-20 w-full" />
          ) : balance.data ? (
            <div className="flex flex-col gap-2 rounded-lg border bg-muted/20 p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-semibold text-2xl tabular-nums">
                  {credits(balance.data.remaining)}
                </span>
                <span className="text-muted-foreground text-sm">
                  of {credits(total)} left · renews{" "}
                  {shortDate(balance.data.renews_at)}
                </span>
              </div>
              <Progress value={leftPercent} className="h-1.5" />
              <p className="text-muted-foreground text-xs">
                {credits(balance.data.allowance)} monthly allowance
                {balance.data.granted > 0 &&
                  ` + ${credits(balance.data.granted)} granted`}{" "}
                · {credits(balance.data.used)} used in {balance.data.period}
              </p>
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-[1fr_1fr]">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="grant-amount">Credits to add</Label>
              <Input
                id="grant-amount"
                type="number"
                min={1}
                value={amount}
                placeholder="500"
                onChange={(e) => setAmount(e.target.value)}
                data-testid="grant-amount"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="grant-days">
                Days{" "}
                <span className="font-normal text-muted-foreground">
                  (optional)
                </span>
              </Label>
              <Input
                id="grant-days"
                type="number"
                min={1}
                max={365}
                value={days}
                placeholder="until month end"
                onChange={(e) => setDays(e.target.value)}
                data-testid="grant-days"
              />
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="grant-reason">
              Reason{" "}
              <span className="font-normal text-muted-foreground">
                (optional)
              </span>
            </Label>
            <Input
              id="grant-reason"
              value={reason}
              placeholder="Migrating five years of invoices"
              onChange={(e) => setReason(e.target.value)}
              data-testid="grant-reason"
            />
          </div>

          {grants.data && grants.data.count > 0 && (
            <div className="flex flex-col gap-1.5">
              <p className="font-medium text-sm">Grants</p>
              <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto">
                {grants.data.data.map((grant) => (
                  <li
                    key={grant.id}
                    className="flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm"
                    data-testid="grant-row"
                  >
                    <span className="font-mono tabular-nums">
                      {credits(grant.credits)}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-muted-foreground">
                      {grant.reason || "No reason given"}
                    </span>
                    <span className="shrink-0 text-muted-foreground text-xs">
                      {grant.expired
                        ? "expired"
                        : `until ${shortDate(grant.expires_at)}`}
                    </span>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      aria-label="Remove grant"
                      disabled={revoke.isPending}
                      onClick={() => revoke.mutate(grant.id)}
                    >
                      <Trash2 />
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={give.isPending}
          >
            Close
          </Button>
          <LoadingButton
            loading={give.isPending}
            disabled={!amount || Number(amount) <= 0}
            onClick={() => give.mutate()}
            data-testid="grant-submit"
          >
            Add credits
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
