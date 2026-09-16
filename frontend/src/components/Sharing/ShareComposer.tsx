import { useQueries } from "@tanstack/react-query"
import { Send } from "lucide-react"
import { useState } from "react"

import type { ShareInvitationPublic, ShareSkipped, UserRef } from "@/client"
import { APP_NAME } from "@/components/Common/Logo"
import { Label } from "@/components/ui/label"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { useDebouncedValue } from "@/hooks/useDebouncedValue"
import { userLookupQuery } from "@/queries/sharing"
import type { RoleOption } from "./AccessList"
import {
  type ChipLookup,
  EmailChipsInput,
  isCompleteEmail,
} from "./EmailChipsInput"

export const MESSAGE_MAX = 1000
/** The batch endpoints accept at most this many addresses in one call. */
export const BATCH_MAX = 50

export const plural = (n: number, one: string, many: string) =>
  n === 1 ? one : many

/**
 * What the recipients are being given.
 *
 * A page share and a space share are the same act at different scales, so they
 * share this whole composer — but they must never claim the same thing, and
 * every sentence that names the grant is built from this.
 */
export type ShareSubject = "page" | "space"

export interface Recipients {
  emails: string[]
  draft: string
  setEmails: (emails: string[]) => void
  setDraft: (draft: string) => void
  /** Lookup outcome per address, for the chips to render. */
  lookups: Map<string, ChipLookup>
  /** Complete addresses, including one still in the field. */
  valid: string[]
  /** Committed chips that are not addresses at all. */
  invalid: string[]
  /** Half-typed text left in the field. */
  draftIncomplete: boolean
  /** How many of the addresses have no account yet. */
  newcomers: number
  tooMany: boolean
  /** Something to send, and nothing broken on the way out. */
  ready: boolean
  clear: () => void
}

/**
 * The address list of a share, with each complete address looked up once.
 *
 * `onEdit` fires whenever the list changes so the caller can drop a report of
 * a previous send: it describes addresses that are no longer on screen.
 */
export function useRecipients(onEdit?: () => void): Recipients {
  const [emails, setEmailsState] = useState<string[]>([])
  const [draft, setDraftState] = useState("")

  const setEmails = (next: string[]) => {
    setEmailsState(next)
    onEdit?.()
  }
  const setDraft = (next: string) => {
    setDraftState(next)
    onEdit?.()
  }

  // An address that was typed but never committed with Enter still counts:
  // people press the button, not the key.
  const pending = draft.trim().toLowerCase()
  const candidates = pending ? [...emails, pending] : emails
  const valid = candidates.filter(isCompleteEmail)
  // Only committed chips are called out as wrong; scolding somebody halfway
  // through typing "col" would be noise.
  const invalid = emails.filter((e) => !isCompleteEmail(e))
  const draftIncomplete = pending !== "" && !isCompleteEmail(pending)

  // Debounced on a joined key rather than the array, whose identity changes on
  // every render and would restart the timer forever.
  const debouncedKey = useDebouncedValue(valid.join(","), 250)
  const lookupEmails = debouncedKey ? debouncedKey.split(",") : []
  const lookupResults = useQueries({
    queries: lookupEmails.map((email) => userLookupQuery(email)),
  })

  const lookups = new Map<string, ChipLookup>()
  for (const email of candidates) {
    if (!isCompleteEmail(email)) {
      lookups.set(email, { status: "invalid" })
      continue
    }
    const index = lookupEmails.indexOf(email)
    const lookup = index >= 0 ? lookupResults[index] : undefined
    if (!lookup || lookup.isPending) {
      lookups.set(email, { status: "pending" })
    } else if (lookup.isError) {
      // We could not find out; say nothing rather than guess.
      lookups.set(email, { status: "unknown" })
    } else if (lookup.data?.exists) {
      lookups.set(email, { status: "known", user: lookup.data.user })
    } else {
      lookups.set(email, { status: "new" })
    }
  }
  const newcomers = [...lookups.values()].filter(
    (l) => l.status === "new",
  ).length
  const tooMany = valid.length > BATCH_MAX

  return {
    emails,
    draft,
    setEmails,
    setDraft,
    lookups,
    valid,
    invalid,
    draftIncomplete,
    newcomers,
    tooMany,
    ready: valid.length > 0 && invalid.length === 0 && !draftIncomplete,
    clear: () => {
      setEmailsState([])
      setDraftState("")
    },
  }
}

interface ShareComposerProps {
  recipients: Recipients
  roles: RoleOption[]
  role: string
  onRoleChange: (role: string) => void
  message: string
  onMessageChange: (message: string) => void
  subject: ShareSubject
  onSubmit: () => void
  submitting: boolean
  /** A reason outside the address list to refuse the send — the limit. */
  blocked?: boolean
}

/**
 * Everything above the access list: who to share with, at what level, with what
 * message. Identical for a page and for a space on purpose — the two are one
 * thing to learn, not two.
 */
export function ShareComposer({
  recipients,
  roles,
  role,
  onRoleChange,
  message,
  onMessageChange,
  subject,
  onSubmit,
  submitting,
  blocked,
}: ShareComposerProps) {
  const canSubmit = recipients.ready && !recipients.tooMany && !blocked
  const { invalid } = recipients

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (canSubmit && !submitting) onSubmit()
      }}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <div className="flex-1">
          <EmailChipsInput
            emails={recipients.emails}
            onChange={recipients.setEmails}
            draft={recipients.draft}
            onDraftChange={recipients.setDraft}
            lookups={recipients.lookups}
            disabled={submitting}
            data-testid="share-email"
          />
          <p className="mt-1 text-xs text-muted-foreground">
            Type an address and press Enter or comma to add it.
          </p>
        </div>
        <Select value={role} onValueChange={onRoleChange}>
          <SelectTrigger
            className="w-full sm:w-36"
            data-testid="share-role"
            aria-label="Access level"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {roles.map((r) => (
              <SelectItem key={r.value} value={r.value}>
                {r.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <LoadingButton
          type="submit"
          loading={submitting}
          disabled={!canSubmit}
          data-testid="share-submit"
        >
          <Send />
          Share
        </LoadingButton>
      </div>

      {invalid.length > 0 && (
        <p className="text-xs text-destructive" data-testid="share-invalid">
          {invalid.join(", ")} {plural(invalid.length, "is", "are")} not a valid
          e-mail address. Remove {plural(invalid.length, "it", "them")} to
          continue.
        </p>
      )}
      {recipients.tooMany && (
        <p className="text-xs text-destructive">
          Share with at most {BATCH_MAX} addresses at a time.
        </p>
      )}
      {recipients.newcomers > 0 && (
        <p
          className="rounded-md bg-muted/60 px-3 py-2 text-xs text-muted-foreground"
          data-testid="share-invite-notice"
        >
          {recipients.newcomers} of these addresses{" "}
          {plural(recipients.newcomers, "doesn't", "don't")} have a {APP_NAME}{" "}
          account yet. They'll get an email inviting them to create one, and the{" "}
          {subject} opens as soon as they confirm it.
        </p>
      )}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="share-message" className="text-xs font-normal">
          Add a message
        </Label>
        <Textarea
          id="share-message"
          rows={2}
          maxLength={MESSAGE_MAX}
          placeholder="Add a message (optional)"
          value={message}
          onChange={(e) => onMessageChange(e.target.value)}
          data-testid="share-message"
        />
        {message.length > 0 && (
          <p className="self-end text-[11px] text-muted-foreground">
            {message.length}/{MESSAGE_MAX}
          </p>
        )}
      </div>
    </form>
  )
}

interface ShareOutcomeProps {
  /**
   * Whoever now has access. A page share answers with document shares and a
   * space share with memberships; only the account behind each is reported, so
   * both fit.
   */
  shared: { user: UserRef }[]
  invited: ShareInvitationPublic[]
  skipped: ShareSkipped[]
  subject: ShareSubject
}

/**
 * What the last send actually did. Access granted, invitations sent and
 * addresses skipped are three different outcomes and are never rolled into one
 * cheerful total: the skipped reasons come from the backend verbatim.
 */
export function ShareOutcome({
  shared,
  invited,
  skipped,
  subject,
}: ShareOutcomeProps) {
  return (
    <div
      className="flex flex-col gap-2 rounded-md border bg-muted/40 p-3 text-xs"
      data-testid="share-result"
    >
      {shared.length > 0 && (
        <p>
          <span className="font-medium text-foreground">
            {shared.length} {plural(shared.length, "person", "people")} now{" "}
            {plural(shared.length, "has", "have")} access
          </span>{" "}
          : {shared.map((s) => s.user.email).join(", ")}
        </p>
      )}
      {invited.length > 0 && (
        <p>
          <span className="font-medium text-foreground">
            {invited.length}{" "}
            {plural(invited.length, "invitation", "invitations")} sent
          </span>{" "}
          : {invited.map((i) => i.email).join(", ")}. The {subject} opens for
          them once they create an account on that address and confirm it.
        </p>
      )}
      {skipped.length > 0 && (
        <ul className="flex flex-col gap-1" data-testid="share-skipped">
          {skipped.map((s) => (
            <li key={s.email} className="text-muted-foreground">
              <span className="font-medium text-foreground">{s.email}</span>:{" "}
              {s.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * How many people this thing is shared with, against the ceiling its owner has.
 * The limit is stated whether or not it has been reached — somebody deciding
 * who to add should not have to discover it by being refused.
 */
export function ShareCounter({
  used,
  limit,
  atLimitMessage,
}: {
  used: number
  limit: number | null
  /** Said only when the ceiling is reached; it must name a way forward. */
  atLimitMessage: string
}) {
  const atLimit = limit !== null && used >= limit
  return (
    <div className="flex items-center justify-between gap-2">
      <span
        className="text-xs text-muted-foreground"
        data-testid="share-recipients"
      >
        {limit === null
          ? `${used} ${plural(used, "person", "people")}`
          : `${used} of ${limit} ${plural(limit, "person", "people")}`}
      </span>
      {atLimit && (
        <span
          className="text-xs text-destructive"
          data-testid="share-limit-reason"
        >
          {atLimitMessage}
        </span>
      )}
    </div>
  )
}
