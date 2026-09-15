import { useQuery } from "@tanstack/react-query"
import { Plus, Trash2, Users } from "lucide-react"
import { useState } from "react"

import type { LimitDefinition, UserGroupPublic } from "@/client"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import {
  limitDefinitionsQuery,
  useCreateUserGroup,
  useDeleteUserGroup,
  userGroupsQuery,
  useUpdateUserGroup,
} from "@/queries/adminGroups"

/**
 * Groups and the settings they carry.
 *
 * The limit fields are generated from `GET /admin/user-groups/limits` rather
 * than written out here, so a limit added to the backend registry appears in
 * this form without this file changing.
 *
 * People are never told which group they are in; this screen is the only place
 * groups exist at all.
 */
export function GroupsPanel() {
  const { data, isPending } = useQuery(userGroupsQuery())
  const { data: definitions } = useQuery(limitDefinitionsQuery())
  const [adding, setAdding] = useState(false)

  const limits = definitions?.data ?? []

  if (isPending) {
    return (
      <div className="flex flex-col gap-3">
        {[0, 1].map((i) => (
          <Skeleton key={i} className="h-44 w-full" />
        ))}
      </div>
    )
  }

  const groups = data?.data ?? []

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="max-w-2xl text-sm text-muted-foreground">
          A group gives a class of accounts the same settings. Everyone starts
          in the default group; moving somebody is invisible to them, and an
          account that runs out of pages is told its number, never its group.
        </p>
        <Button
          size="sm"
          onClick={() => setAdding(true)}
          data-testid="new-group"
        >
          <Plus />
          New group
        </Button>
      </div>

      {adding && (
        <NewGroupCard limits={limits} onDone={() => setAdding(false)} />
      )}

      {groups.map((group) => (
        <GroupCard key={group.id} group={group} limits={limits} />
      ))}
    </div>
  )
}

function limitValue(
  group: UserGroupPublic,
  key: string,
): number | null | undefined {
  return (group as unknown as Record<string, number | null>)[key]
}

function effectiveValue(group: UserGroupPublic, key: string): number {
  const record = group as unknown as Record<string, number>
  return record[`effective_${key}`] ?? 0
}

function NewGroupCard({
  limits,
  onDone,
}: {
  limits: LimitDefinition[]
  onDone: () => void
}) {
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [values, setValues] = useState<Record<string, string>>({})
  const create = useCreateUserGroup()

  return (
    <Card data-testid="new-group-card">
      <CardHeader>
        <CardTitle className="text-base">New group</CardTitle>
        <CardDescription>
          Leave a number blank to inherit it from the default group.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="group-name">Name</Label>
            <Input
              id="group-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Contractors"
              data-testid="group-name"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="group-description">Description</Label>
            <Textarea
              id="group-description"
              rows={1}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this group is for"
            />
          </div>
        </div>

        <LimitFields
          limits={limits}
          values={values}
          onChange={(key, value) =>
            setValues((prev) => ({ ...prev, [key]: value }))
          }
          placeholderFor={(limit) => `${limit.default} (inherited)`}
        />

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onDone}>
            Cancel
          </Button>
          <LoadingButton
            loading={create.isPending}
            disabled={!name.trim()}
            data-testid="create-group"
            onClick={() =>
              create.mutate(
                {
                  name: name.trim(),
                  description: description.trim() || null,
                  ...numbersFrom(values),
                },
                { onSuccess: onDone },
              )
            }
          >
            Create group
          </LoadingButton>
        </div>
      </CardContent>
    </Card>
  )
}

function GroupCard({
  group,
  limits,
}: {
  group: UserGroupPublic
  limits: LimitDefinition[]
}) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [confirming, setConfirming] = useState(false)
  const update = useUpdateUserGroup()
  const remove = useDeleteUserGroup()

  const current = (key: string) => {
    if (key in values) return values[key]
    const own = limitValue(group, key)
    return own === null || own === undefined ? "" : String(own)
  }

  return (
    <Card data-testid="group-card">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-base">
              {group.name}
              {group.is_default && (
                <span className="rounded bg-muted px-1.5 py-0.5 text-xs font-normal text-muted-foreground">
                  default
                </span>
              )}
            </CardTitle>
            <CardDescription className="flex items-center gap-1.5">
              <Users className="size-3.5" />
              {group.member_count}{" "}
              {group.member_count === 1 ? "account" : "accounts"}
              {group.description && <> · {group.description}</>}
            </CardDescription>
          </div>
          {!group.is_system && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`Delete ${group.name}`}
              onClick={() => setConfirming(true)}
              data-testid="delete-group"
            >
              <Trash2 className="size-4" />
            </Button>
          )}
        </div>
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        <LimitFields
          limits={limits}
          values={Object.fromEntries(
            limits.map((l) => [l.key, current(l.key)]),
          )}
          onChange={(key, value) =>
            setValues((prev) => ({ ...prev, [key]: value }))
          }
          placeholderFor={(limit) =>
            group.is_default
              ? String(limit.default)
              : `${effectiveValue(group, limit.key)} (inherited)`
          }
        />

        <div className="flex justify-end">
          <LoadingButton
            size="sm"
            loading={update.isPending}
            disabled={Object.keys(values).length === 0}
            data-testid="save-group"
            onClick={() =>
              update.mutate(
                { id: group.id, body: numbersFrom(values) },
                { onSuccess: () => setValues({}) },
              )
            }
          >
            Save
          </LoadingButton>
        </div>
      </CardContent>

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete “{group.name}”?</AlertDialogTitle>
            <AlertDialogDescription>
              Its {group.member_count}{" "}
              {group.member_count === 1 ? "account goes" : "accounts go"} back
              to the default group's settings. Nothing they have made is
              touched.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              data-testid="confirm-delete-group"
              onClick={() => remove.mutate(group.id)}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

/** One number per administrable limit, blank meaning inherit. */
export function LimitFields({
  limits,
  values,
  onChange,
  placeholderFor,
}: {
  limits: LimitDefinition[]
  values: Record<string, string>
  onChange: (key: string, value: string) => void
  placeholderFor: (limit: LimitDefinition) => string
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {limits.map((limit) => (
        <div key={limit.key} className="flex flex-col gap-1.5">
          <Label htmlFor={`limit-${limit.key}`}>{limit.label}</Label>
          <Input
            id={`limit-${limit.key}`}
            type="number"
            min={limit.minimum ?? 0}
            max={limit.maximum ?? undefined}
            value={values[limit.key] ?? ""}
            // The inherited number is the placeholder, so an empty box visibly
            // reads as the value it would fall back to.
            placeholder={placeholderFor(limit)}
            onChange={(e) => onChange(limit.key, e.target.value)}
            data-testid={`limit-${limit.key}`}
          />
          <p className="text-xs text-muted-foreground">{limit.description}</p>
        </div>
      ))}
    </div>
  )
}

/** Blank stays blank: an empty field is "inherit", not zero. */
export function numbersFrom(
  values: Record<string, string>,
): Record<string, number | null> {
  const out: Record<string, number | null> = {}
  for (const [key, raw] of Object.entries(values)) {
    const trimmed = raw.trim()
    out[key] = trimmed === "" ? null : Number(trimmed)
  }
  return out
}
