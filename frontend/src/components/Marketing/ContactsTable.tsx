import { useQuery } from "@tanstack/react-query"
import { Ban, Search, Trash2, Upload, UserPlus } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
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
  type ContactFilters,
  contactIdsQuery,
  contactsQuery,
  useAddContact,
  useDeleteContact,
  useImportContacts,
  useUnsubscribeContact,
} from "@/queries/adminMarketing"

const PAGE = 50

/**
 * The list, and who the next campaign goes to.
 *
 * Selection is carried out of here rather than kept here, because the composer
 * is what needs it. "Select all" fetches the ids matching the current filter
 * instead of ticking the page: a page is fifty rows and the list is hundreds,
 * and a control that says "all" and means "these fifty" is the kind of thing
 * somebody discovers after sending.
 */
export function ContactsTable({
  selected,
  onSelectedChange,
}: {
  selected: Set<string>
  onSelectedChange: (next: Set<string>) => void
}) {
  const [q, setQ] = useState("")
  const [subscribed, setSubscribed] = useState<"all" | "yes" | "no">("yes")
  const [page, setPage] = useState(0)
  const [adding, setAdding] = useState(false)

  const filters: ContactFilters = {
    q,
    subscribed: subscribed === "all" ? undefined : subscribed === "yes",
    skip: page * PAGE,
    limit: PAGE,
  }
  const { data, isPending } = useQuery(contactsQuery(filters))
  const [wantAll, setWantAll] = useState(false)
  const everyone = useQuery(contactIdsQuery(filters, wantAll))

  const remove = useDeleteContact()
  const unsubscribe = useUnsubscribeContact()
  const importFile = useImportContacts()
  const fileRef = useRef<HTMLInputElement | null>(null)

  const rows = data?.data ?? []
  const total = data?.count ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE))

  const toggle = (id: string) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onSelectedChange(next)
  }

  const selectEverything = async () => {
    setWantAll(true)
    const ids = everyone.data ?? (await everyone.refetch()).data
    if (ids) onSelectedChange(new Set(ids))
  }

  return (
    <div
      className="flex min-w-0 flex-col gap-3"
      data-testid="marketing-contacts"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 sm:max-w-xs">
          <Search className="-translate-y-1/2 absolute top-1/2 left-2.5 size-4 text-muted-foreground" />
          <Input
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              setPage(0)
            }}
            placeholder="Search name or address"
            aria-label="Search contacts"
            className="min-w-0 pl-8"
            data-testid="marketing-search"
          />
        </div>
        <Select
          value={subscribed}
          onValueChange={(v) => {
            setSubscribed(v as "all" | "yes" | "no")
            setPage(0)
          }}
        >
          <SelectTrigger className="w-44" data-testid="marketing-filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="yes">Subscribed</SelectItem>
            <SelectItem value="no">Unsubscribed</SelectItem>
            <SelectItem value="all">Everyone</SelectItem>
          </SelectContent>
        </Select>

        <div className="ms-auto flex items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ""
              if (!file) return
              importFile.mutate(file, {
                onSuccess: (result) => {
                  if (!result) return
                  toast.success(
                    `${result.added} added, ${result.already_present} already on the list` +
                      (result.skipped?.length
                        ? `, ${result.skipped.length} skipped`
                        : ""),
                  )
                },
              })
            }}
          />
          <LoadingButton
            variant="outline"
            size="sm"
            loading={importFile.isPending}
            onClick={() => fileRef.current?.click()}
            data-testid="marketing-import"
          >
            <Upload />
            Import CSV
          </LoadingButton>
          <Button
            size="sm"
            onClick={() => setAdding(true)}
            data-testid="marketing-add"
          >
            <UserPlus />
            Add
          </Button>
        </div>
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-2 text-muted-foreground text-sm">
        <span data-testid="marketing-selected-count">
          {selected.size} of {total} selected
        </span>
        <Button
          variant="link"
          size="sm"
          onClick={() => void selectEverything()}
          data-testid="marketing-select-all"
        >
          Select all {total}
        </Button>
        {selected.size > 0 && (
          <Button
            variant="link"
            size="sm"
            onClick={() => onSelectedChange(new Set())}
          >
            Clear
          </Button>
        )}
      </div>

      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10" />
              <TableHead>Address</TableHead>
              <TableHead className="hidden sm:table-cell">Name</TableHead>
              <TableHead className="hidden md:table-cell">Added</TableHead>
              <TableHead className="w-24" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isPending &&
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={5}>
                    <Skeleton className="h-5 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {!isPending && rows.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={5}
                  className="text-muted-foreground text-sm"
                >
                  Nobody here yet. Import a CSV, or add one address.
                </TableCell>
              </TableRow>
            )}
            {rows.map((contact) => (
              <TableRow key={contact.id} data-testid="marketing-contact-row">
                <TableCell>
                  <Checkbox
                    checked={selected.has(contact.id)}
                    onCheckedChange={() => toggle(contact.id)}
                    aria-label={`Select ${contact.email}`}
                    disabled={!contact.subscribed}
                  />
                </TableCell>
                <TableCell className="min-w-0">
                  <span className="wrap-anywhere">{contact.email}</span>
                  {!contact.subscribed && (
                    <Badge variant="outline" className="ms-2 shrink-0">
                      Unsubscribed
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="hidden min-w-0 sm:table-cell">
                  <span className="wrap-anywhere">
                    {contact.name || "Not given"}
                  </span>
                </TableCell>
                <TableCell className="hidden whitespace-nowrap text-muted-foreground text-sm md:table-cell">
                  {relativeTime(contact.created_at)}
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-end gap-1">
                    {contact.subscribed && (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Unsubscribe"
                        onClick={() => unsubscribe.mutate(contact.id)}
                      >
                        <Ban />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Delete"
                      className="text-destructive"
                      onClick={() => remove.mutate(contact.id)}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-between gap-2 text-sm">
          <span className="text-muted-foreground">
            Page {page + 1} of {pages}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page + 1 >= pages}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      <AddContactDialog open={adding} onOpenChange={setAdding} />
    </div>
  )
}

function AddContactDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [email, setEmail] = useState("")
  const [name, setName] = useState("")
  const add = useAddContact()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" data-testid="marketing-add-dialog">
        <DialogHeader>
          <DialogTitle>Add a contact</DialogTitle>
          <DialogDescription>
            One address. Use Import CSV for a list.
          </DialogDescription>
        </DialogHeader>
        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="marketing-new-email">Address</Label>
            <Input
              id="marketing-new-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="someone@example.com"
              data-testid="marketing-new-email"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="marketing-new-name">Name</Label>
            <Input
              id="marketing-new-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Optional"
              data-testid="marketing-new-name"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton
            loading={add.isPending}
            onClick={() =>
              add.mutate(
                { email: email.trim(), name: name.trim() },
                {
                  onSuccess: () => {
                    setEmail("")
                    setName("")
                    onOpenChange(false)
                  },
                },
              )
            }
            data-testid="marketing-new-save"
          >
            Add
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
