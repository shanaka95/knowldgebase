import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import type { AdminUserPublic } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  limitDefinitionsQuery,
  userGroupsQuery,
  useSetUserAssignment,
} from "@/queries/adminGroups"
import { LimitFields, numbersFrom } from "./GroupsPanel"

const NO_GROUP = "__none__"

/**
 * Which group an account is in, and anything it overrides.
 *
 * Deliberately not part of "Edit user": that dialog is identity, password and
 * roles, and keeping grouping out of it is what lets the ordinary user shapes
 * stay free of any mention of groups.
 *
 * Overrides are sent as a complete map rather than a patch, so an empty field
 * simply is not in it. That removes the usual three-way muddle between "not
 * sent", "sent as null" and "sent as a number".
 */
export function UserAssignmentDialog({
  user,
  open,
  onOpenChange,
}: {
  user: AdminUserPublic
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { data: groups } = useQuery(userGroupsQuery())
  const { data: definitions } = useQuery(limitDefinitionsQuery())
  const save = useSetUserAssignment()

  const limits = definitions?.data ?? []
  const byKey = new Map((user.limits ?? []).map((l) => [l.key, l]))

  const [groupId, setGroupId] = useState(user.group?.id ?? NO_GROUP)
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      (user.limits ?? []).map((l) => [
        l.key,
        l.override === null || l.override === undefined
          ? ""
          : String(l.override),
      ]),
    ),
  )

  const inherited = (key: string) => {
    const limit = byKey.get(key)
    if (!limit) return ""
    // What they would get if this override were cleared.
    const fallback = limit.group_value ?? limit.default_value ?? 0
    return `${fallback} (inherited)`
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl" data-testid="assignment-dialog">
        <DialogHeader>
          <DialogTitle>Group and limits</DialogTitle>
          <DialogDescription>
            {user.full_name || user.email}. None of this is shown to them. An
            account that reaches a limit sees the number it hit, not where the
            number came from.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="assignment-group">Group</Label>
            <Select value={groupId} onValueChange={setGroupId}>
              <SelectTrigger
                id="assignment-group"
                data-testid="assignment-group"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_GROUP}>
                  No group (uses the defaults)
                </SelectItem>
                {(groups?.data ?? []).map((group) => (
                  <SelectItem key={group.id} value={group.id}>
                    {group.name}
                    {group.is_default ? " (default)" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <p className="mb-2 text-sm font-medium">
              Overrides for this account
            </p>
            <LimitFields
              limits={limits}
              values={values}
              onChange={(key, value) =>
                setValues((prev) => ({ ...prev, [key]: value }))
              }
              placeholderFor={(limit) => inherited(limit.key)}
            />
            <p className="mt-2 text-xs text-muted-foreground">
              Leave a box empty to inherit. The greyed number is what they would
              get without an override.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton
            loading={save.isPending}
            data-testid="save-assignment"
            onClick={() =>
              save.mutate(
                {
                  userId: user.id,
                  body: {
                    group_id: groupId === NO_GROUP ? null : groupId,
                    // Only the boxes with something in them travel: an empty
                    // one is an override that is not set.
                    overrides: Object.fromEntries(
                      Object.entries(numbersFrom(values)).filter(
                        ([, value]) => value !== null,
                      ),
                    ) as Record<string, number>,
                  },
                },
                { onSuccess: () => onOpenChange(false) },
              )
            }
          >
            Save
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
