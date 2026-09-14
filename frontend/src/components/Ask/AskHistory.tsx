import { useInfiniteQuery } from "@tanstack/react-query"
import {
  formatDistanceToNowStrict,
  isThisWeek,
  isToday,
  isYesterday,
} from "date-fns"
import {
  FileText,
  MessageSquarePlus,
  MoreHorizontal,
  Pencil,
  Trash2,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"

import type { AskConversationPublic } from "@/client"
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import {
  conversationsQuery,
  useDeleteConversation,
  useRenameConversation,
} from "@/queries/askConversations"

interface AskHistoryProps {
  activeId: string | undefined
  onOpen: (conversation: AskConversationPublic) => void
  onNew: () => void
}

/** Threads in the buckets people actually think in. */
function bucketOf(iso: string): string {
  const date = new Date(iso)
  if (isToday(date)) return "Today"
  if (isYesterday(date)) return "Yesterday"
  if (isThisWeek(date, { weekStartsOn: 1 })) return "Earlier this week"
  return "Older"
}

export function AskHistory({ activeId, onOpen, onNew }: AskHistoryProps) {
  const { data, isPending, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery(conversationsQuery())
  const [renaming, setRenaming] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<AskConversationPublic | null>(null)
  const rename = useRenameConversation()
  const remove = useDeleteConversation()
  const sentinel = useRef<HTMLDivElement>(null)

  // The next page is fetched when the bottom of the list comes into view,
  // rather than all of them up front.
  useEffect(() => {
    const node = sentinel.current
    if (!node || !hasNextPage) return
    const observer = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting) void fetchNextPage()
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [fetchNextPage, hasNextPage])

  const conversations = (data?.pages ?? []).flatMap((page) => page.data)

  const groups: [string, AskConversationPublic[]][] = []
  for (const conversation of conversations) {
    const bucket = bucketOf(conversation.updated_at)
    const last = groups[groups.length - 1]
    if (last && last[0] === bucket) last[1].push(conversation)
    else groups.push([bucket, [conversation]])
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium">Chats</h2>
        <Button
          variant="outline"
          size="sm"
          onClick={onNew}
          data-testid="ask-new-chat"
        >
          <MessageSquarePlus className="size-3.5" />
          New
        </Button>
      </div>

      <div className="-mr-2 min-h-0 flex-1 overflow-y-auto pr-2">
        {isPending && (
          <div className="flex flex-col gap-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        )}

        {!isPending && conversations.length === 0 && (
          <p className="px-1 text-xs text-muted-foreground">
            Your questions are kept here, so you can pick a thread back up
            later.
          </p>
        )}

        {groups.map(([bucket, items]) => (
          <div key={bucket} className="mb-3 flex flex-col gap-0.5">
            <p className="px-1 pb-1 text-[0.7rem] font-medium uppercase tracking-wide text-muted-foreground">
              {bucket}
            </p>
            {items.map((conversation) => (
              <HistoryRow
                key={conversation.id}
                conversation={conversation}
                active={conversation.id === activeId}
                renaming={renaming === conversation.id}
                onOpen={() => onOpen(conversation)}
                onStartRename={() => setRenaming(conversation.id)}
                onFinishRename={(title) => {
                  setRenaming(null)
                  const next = title.trim()
                  if (next && next !== conversation.title) {
                    rename.mutate({ id: conversation.id, title: next })
                  }
                }}
                onDelete={() => setDeleting(conversation)}
              />
            ))}
          </div>
        ))}

        <div ref={sentinel} className="h-1" />
        {isFetchingNextPage && <Skeleton className="mt-1 h-9 w-full" />}
      </div>

      <AlertDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this chat?</AlertDialogTitle>
            <AlertDialogDescription>
              “{deleting?.title}” and its answers are removed. The pages it
              cited are untouched.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (deleting) remove.mutate(deleting.id)
                setDeleting(null)
              }}
              data-testid="ask-confirm-delete"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

/** A thread's length as the reader counts it: questions, not messages. */
function questionCount(conversation: AskConversationPublic): string {
  const asked = Math.max(1, Math.round((conversation.message_count ?? 0) / 2))
  return `${asked} question${asked === 1 ? "" : "s"}`
}

function HistoryRow({
  conversation,
  active,
  renaming,
  onOpen,
  onStartRename,
  onFinishRename,
  onDelete,
}: {
  conversation: AskConversationPublic
  active: boolean
  renaming: boolean
  onOpen: () => void
  onStartRename: () => void
  onFinishRename: (title: string) => void
  onDelete: () => void
}) {
  const [draft, setDraft] = useState(conversation.title)

  useEffect(() => {
    if (renaming) setDraft(conversation.title)
  }, [renaming, conversation.title])

  if (renaming) {
    return (
      <Input
        autoFocus
        value={draft}
        maxLength={120}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => onFinishRename(draft)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onFinishRename(draft)
          if (e.key === "Escape") onFinishRename(conversation.title)
        }}
        className="h-9 text-sm"
        data-testid="ask-rename-input"
      />
    )
  }

  return (
    <div
      className={cn(
        "group flex items-center gap-1 rounded-md pr-1 transition-colors",
        active ? "bg-accent" : "hover:bg-accent/50",
      )}
    >
      <button
        type="button"
        onClick={onOpen}
        className="min-w-0 flex-1 px-2 py-1.5 text-left"
        data-testid="ask-history-item"
        data-active={active}
      >
        <span className="flex items-center gap-1.5">
          {conversation.document_id && (
            <FileText className="size-3 shrink-0 text-muted-foreground" />
          )}
          <span className="truncate text-sm">{conversation.title}</span>
        </span>
        <span className="block truncate text-[0.7rem] text-muted-foreground">
          {conversation.document_title ?? questionCount(conversation)}
          {" · "}
          {formatDistanceToNowStrict(new Date(conversation.updated_at))} ago
        </span>
      </button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            className="size-7 shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
            aria-label={`Actions for ${conversation.title}`}
            data-testid="ask-history-menu"
          >
            <MoreHorizontal className="size-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-40">
          <DropdownMenuItem onSelect={onStartRename}>
            <Pencil />
            Rename
          </DropdownMenuItem>
          <DropdownMenuItem variant="destructive" onSelect={onDelete}>
            <Trash2 />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
