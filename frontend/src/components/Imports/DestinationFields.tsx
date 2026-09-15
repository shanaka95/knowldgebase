import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, CornerDownRight, Plus, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { type NamespacePublic, NamespacesService } from "@/client"
import { NamespaceIcon } from "@/components/Namespaces/NamespaceIcon"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useCreateFolder } from "@/hooks/useKbMutations"
import { queryKeys } from "@/lib/queryKeys"
import { foldersInTreeOrder, treeQuery } from "@/queries/namespaces"

/**
 * Where a document is about to land: which space, and which folder in it.
 *
 * One component rather than one per way of getting a file in, because the
 * answer to "where does this go" should not depend on whether the file came
 * from a phone camera, a file picker or a Drive - and a folder hierarchy that
 * reads correctly in one place and not the other is worse than either.
 *
 * Both lists can create what they are missing. Filing something is the moment
 * you discover the place for it does not exist yet, and the alternative is
 * abandoning the upload, going elsewhere to make a folder, and starting again.
 * The new one is selected straight away, because making it was never the point.
 */

const NEW = "__new__"
const ROOT = "__root__"

export function DestinationFields({
  spaces,
  spaceId,
  onSpaceChange,
  folderId,
  onFolderChange,
  disabled = false,
  idPrefix = "destination",
}: {
  spaces: NamespacePublic[]
  spaceId: string
  onSpaceChange: (id: string) => void
  folderId: string | null
  onFolderChange: (id: string | null) => void
  disabled?: boolean
  idPrefix?: string
}) {
  const queryClient = useQueryClient()
  const { data: tree } = useQuery({
    ...treeQuery(spaceId),
    enabled: Boolean(spaceId),
  })
  const folders = tree?.raw.folders ?? []

  const [namingSpace, setNamingSpace] = useState(false)
  const [namingFolder, setNamingFolder] = useState(false)

  const createSpace = useMutation({
    mutationFn: async (name: string) =>
      (await NamespacesService.createNamespace({ body: { name } })).data,
    onSuccess: async (ns) => {
      // Awaited, not fired and forgotten: the list this select renders from
      // lives in the parent, and selecting an id it does not have yet leaves
      // the trigger blank until the refetch happens to land.
      await queryClient.invalidateQueries({
        queryKey: queryKeys.namespaces.all,
      })
      onSpaceChange(ns.id)
      onFolderChange(null)
      setNamingSpace(false)
    },
  })

  const createFolder = useCreateFolder()

  // Where a new folder would go, said plainly: "inside the folder you have
  // selected" is useful and surprising if it is not spelled out.
  const parent = folders.find((f) => f.id === folderId)
  const parentLabel = parent ? parent.name : "the space root"

  if (namingSpace) {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <InlineCreate
          label="New space"
          placeholder="Space name"
          hint="A new space, with you as its only member"
          testId={`${idPrefix}-new-space`}
          pending={createSpace.isPending}
          error={createSpace.error}
          onCancel={() => {
            createSpace.reset()
            setNamingSpace(false)
          }}
          onSubmit={(name) => createSpace.mutate(name)}
        />
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div className="flex flex-col gap-2">
        <Label htmlFor={`${idPrefix}-space`}>Space</Label>
        <Select
          value={spaceId}
          onValueChange={(value) => {
            if (value === NEW) {
              setNamingSpace(true)
              return
            }
            onSpaceChange(value)
            onFolderChange(null)
          }}
          disabled={disabled}
        >
          <SelectTrigger
            id={`${idPrefix}-space`}
            className="w-full"
            data-testid={`${idPrefix}-space-select`}
          >
            <SelectValue placeholder="Select a space" />
          </SelectTrigger>
          <SelectContent>
            {/*
              First, not last. The list is as long as somebody's account is
              old, and an action at the bottom of thirty folders is an action
              behind a scroll - which is where it was, in a screenshot, after
              a dozen test runs.
            */}
            <SelectItem
              value={NEW}
              data-testid={`${idPrefix}-new-space-option`}
            >
              <span className="flex items-center gap-2 text-muted-foreground">
                <Plus className="size-3.5" />
                New space…
              </span>
            </SelectItem>
            {spaces.length > 0 && <SelectSeparator />}
            {spaces.map((ns) => (
              <SelectItem key={ns.id} value={ns.id}>
                <span className="flex items-center gap-2">
                  <NamespaceIcon icon={ns.icon} color={ns.color} size="xs" />
                  {ns.name}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor={`${idPrefix}-folder`}>Folder</Label>
        {namingFolder ? (
          <InlineCreate
            label={null}
            placeholder="Folder name"
            hint={`Created in ${parentLabel}`}
            testId={`${idPrefix}-new-folder`}
            pending={createFolder.isPending}
            error={createFolder.error}
            onCancel={() => {
              createFolder.reset()
              setNamingFolder(false)
            }}
            onSubmit={(name) =>
              createFolder.mutate(
                { namespaceId: spaceId, parentId: folderId, name },
                {
                  onSuccess: (folder) => {
                    onFolderChange(folder.id)
                    setNamingFolder(false)
                  },
                },
              )
            }
          />
        ) : (
          <Select
            value={folderId ?? ROOT}
            onValueChange={(value) => {
              if (value === NEW) {
                setNamingFolder(true)
                return
              }
              onFolderChange(value === ROOT ? null : value)
            }}
            disabled={disabled || !spaceId}
          >
            <SelectTrigger
              id={`${idPrefix}-folder`}
              className="w-full"
              data-testid={`${idPrefix}-folder-select`}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem
                value={NEW}
                data-testid={`${idPrefix}-new-folder-option`}
              >
                <span className="flex items-center gap-2 text-muted-foreground">
                  <Plus className="size-3.5" />
                  New folder in {parentLabel}…
                </span>
              </SelectItem>
              <SelectSeparator />
              <SelectItem value={ROOT}>Space root</SelectItem>
              {/*
                Indented by depth, so a nested folder reads as nested. A flat
                list cannot distinguish a top-level "Invoices" from one of three
                under different parents, which leaves the reader guessing where a
                document is about to go.
              */}
              {foldersInTreeOrder(folders).map(({ folder, depth }) => (
                <SelectItem key={folder.id} value={folder.id}>
                  <span
                    style={{ paddingInlineStart: `${depth * 14}px` }}
                    className="flex min-w-0 items-center gap-1.5"
                  >
                    {depth > 0 && (
                      <CornerDownRight
                        className="size-3 shrink-0 text-muted-foreground"
                        aria-hidden
                      />
                    )}
                    <span className="truncate">{folder.name}</span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>
    </div>
  )
}

/**
 * Naming the thing, in the place the dropdown was.
 *
 * In place rather than in a second dialog: a dialog on top of a dialog loses
 * the upload behind it, and everything here is one field and two buttons.
 * Enter creates, Escape goes back — the keys somebody already expects.
 */
function InlineCreate({
  label,
  placeholder,
  hint,
  testId,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  label: string | null
  placeholder: string
  hint?: string
  testId: string
  pending: boolean
  error: unknown
  onSubmit: (name: string) => void
  onCancel: () => void
}) {
  const [name, setName] = useState("")
  const ref = useRef<HTMLInputElement>(null)
  // Held in a ref so the listener below never closes over a stale callback.
  const cancel = useRef(onCancel)
  cancel.current = onCancel

  useEffect(() => {
    const input = ref.current
    input?.focus()
    if (!input) return

    // A native listener in the capture phase, because React's
    // `stopPropagation` cannot reach the document-level handler Radix's
    // dismissable layer installs - so Escape closed the whole upload dialog
    // and took the chosen files with it. Escape here means "not this name",
    // never "not this upload".
    const swallow = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return
      if (!input.contains(event.target as Node) && event.target !== input)
        return
      event.preventDefault()
      event.stopImmediatePropagation()
      cancel.current()
    }
    document.addEventListener("keydown", swallow, true)
    return () => document.removeEventListener("keydown", swallow, true)
  }, [])

  const submit = () => {
    const trimmed = name.trim()
    if (trimmed) onSubmit(trimmed)
  }

  return (
    <div className="flex flex-col gap-2">
      {label && <Label htmlFor={testId}>{label}</Label>}
      <div className="flex items-center gap-1.5">
        <Input
          id={testId}
          ref={ref}
          value={name}
          placeholder={placeholder}
          disabled={pending}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault()
              submit()
            }
            // Escape is handled by a native capture listener above.
          }}
          data-testid={testId}
        />
        <Button
          size="icon"
          variant="secondary"
          aria-label="Create"
          disabled={pending || !name.trim()}
          onClick={submit}
          data-testid={`${testId}-confirm`}
        >
          <Check />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          aria-label="Cancel"
          disabled={pending}
          onClick={onCancel}
          data-testid={`${testId}-cancel`}
        >
          <X />
        </Button>
      </div>
      {error instanceof Error ? (
        <p className="text-destructive text-xs">{error.message}</p>
      ) : (
        hint && <p className="text-muted-foreground text-xs">{hint}</p>
      )}
    </div>
  )
}
