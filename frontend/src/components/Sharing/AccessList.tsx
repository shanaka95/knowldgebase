import { Clock, Crown, Trash2 } from "lucide-react"

import type { ShareInvitationPublic, UserRef } from "@/client"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import useAuth from "@/hooks/useAuth"
import { shortDate } from "@/lib/format"
import { getInitials } from "@/utils"

export interface ShareRow {
  user: UserRef
  role: string
  isOwner?: boolean
}

export interface RoleOption {
  value: string
  label: string
  hint: string
}

interface AccessListProps {
  roles: RoleOption[]
  rows: ShareRow[] | undefined
  isPending: boolean
  onUpdateRole: (userId: string, role: string) => void
  onRemove: (userId: string) => void
  removing?: boolean
  /** Addresses invited but not yet accepted. Documents only. */
  invitations?: ShareInvitationPublic[]
  onWithdraw?: (invitationId: string) => void
  withdrawing?: boolean
  emptyText?: string
  /** False turns the list read-only — the backend refuses these edits anyway. */
  canManage?: boolean
}

/**
 * Everyone who can reach the thing being shared, in one list: people who have
 * access now, and — for a page — addresses that were invited and have not
 * confirmed yet. The two are drawn differently on purpose; an invitation is a
 * promise of access, not access.
 */
export function AccessList({
  roles,
  rows,
  isPending,
  onUpdateRole,
  onRemove,
  removing,
  invitations = [],
  onWithdraw,
  withdrawing,
  emptyText = "Nobody has been added yet.",
  canManage = true,
}: AccessListProps) {
  const { user: me } = useAuth()
  const isEmpty = (rows?.length ?? 0) === 0 && invitations.length === 0

  return (
    <div className="flex flex-col divide-y rounded-md border">
      {isPending && (
        <div className="flex flex-col gap-3 p-3">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      )}
      {!isPending && isEmpty && (
        <p className="p-4 text-center text-sm text-muted-foreground">
          {emptyText}
        </p>
      )}
      {rows?.map((row) => {
        const isMe = row.user.id === me?.id
        return (
          <div
            key={row.user.id}
            className="flex items-center gap-3 px-3 py-2"
            data-testid="share-row"
          >
            <Avatar className="size-8">
              <AvatarFallback className="text-xs">
                {getInitials(row.user.full_name || row.user.email)}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {row.user.full_name || row.user.email}
                {isMe && <span className="text-muted-foreground"> (you)</span>}
              </p>
              {row.user.full_name && (
                <p className="truncate text-xs text-muted-foreground">
                  {row.user.email}
                </p>
              )}
            </div>
            {row.isOwner || !canManage ? (
              <span className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground">
                {row.isOwner && <Crown className="size-3.5" />}
                {row.isOwner
                  ? "Owner"
                  : (roles.find((r) => r.value === row.role)?.label ??
                    row.role)}
              </span>
            ) : (
              <>
                <Select
                  value={row.role}
                  onValueChange={(role) => onUpdateRole(row.user.id, role)}
                >
                  <SelectTrigger className="h-8 w-32 text-xs" aria-label="Role">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {roles.map((r) => (
                      <SelectItem key={r.value} value={r.value}>
                        <span className="flex flex-col items-start">
                          <span>{r.label}</span>
                          <span className="text-xs text-muted-foreground">
                            {r.hint}
                          </span>
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Remove ${row.user.email}`}
                  onClick={() => onRemove(row.user.id)}
                  disabled={removing}
                >
                  <Trash2 className="size-4 text-muted-foreground" />
                </Button>
              </>
            )}
          </div>
        )
      })}
      {invitations.map((invitation) => (
        <div
          key={invitation.id}
          className="flex items-center gap-3 px-3 py-2"
          data-testid="invitation-row"
        >
          <Avatar className="size-8">
            <AvatarFallback className="bg-transparent">
              <Clock className="size-4 text-muted-foreground" />
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{invitation.email}</p>
            <p className="truncate text-xs text-muted-foreground">
              Invited — not yet accepted · expires{" "}
              {shortDate(invitation.expires_at)}
            </p>
          </div>
          <span className="text-xs text-muted-foreground">
            {roles.find((r) => r.value === invitation.role)?.label ??
              invitation.role}
          </span>
          {onWithdraw && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`Withdraw the invitation for ${invitation.email}`}
              onClick={() => onWithdraw(invitation.id)}
              disabled={withdrawing}
            >
              <Trash2 className="size-4 text-muted-foreground" />
            </Button>
          )}
        </div>
      ))}
    </div>
  )
}
