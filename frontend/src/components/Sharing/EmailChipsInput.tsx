import { UserPlus, X } from "lucide-react"
import { useState } from "react"
import { z } from "zod"

import type { UserRef } from "@/client"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Spinner } from "@/components/ui/spinner"
import { cn } from "@/lib/utils"
import { getInitials } from "@/utils"

const emailSchema = z.email()

/**
 * Whether a value is a complete address rather than something half-typed.
 *
 * The lookup endpoint answers exact addresses only and rejects anything else,
 * so this is the gate in front of it: never ask about "col", only about
 * "colleague@company.com".
 */
export function isCompleteEmail(value: string): boolean {
  return emailSchema.safeParse(value.trim()).success
}

/** "unknown" means the lookup could not be made; the chip then claims nothing. */
export type ChipStatus = "invalid" | "pending" | "known" | "new" | "unknown"

export interface ChipLookup {
  status: ChipStatus
  user?: UserRef | null
}

interface EmailChipsInputProps {
  emails: string[]
  onChange: (emails: string[]) => void
  /** Lookup outcome per address, keyed by the address itself. */
  lookups: Map<string, ChipLookup>
  disabled?: boolean
  placeholder?: string
  "data-testid"?: string
}

/** Split pasted text the way people actually paste address lists. */
function splitCandidates(raw: string): string[] {
  return raw
    .split(/[,;\s]+/)
    .map((part) => part.trim())
    .filter(Boolean)
}

function Chip({
  email,
  lookup,
  disabled,
  onRemove,
}: {
  email: string
  lookup: ChipLookup
  disabled?: boolean
  onRemove: () => void
}) {
  const name = lookup.user?.full_name || lookup.user?.email || email
  return (
    <span
      className={cn(
        "flex max-w-full items-center gap-1.5 rounded-full border py-0.5 pr-1 pl-1.5 text-xs",
        lookup.status === "invalid"
          ? "border-destructive/50 bg-destructive/10 text-destructive"
          : "bg-muted/60",
      )}
      data-testid="share-chip"
      data-status={lookup.status}
      title={
        lookup.status === "invalid"
          ? `${email} is not a valid e-mail address`
          : email
      }
    >
      {lookup.status === "pending" && (
        <Spinner className="size-3.5 text-muted-foreground" />
      )}
      {lookup.status === "known" && (
        <Avatar className="size-4">
          <AvatarFallback className="text-[8px]">
            {getInitials(name)}
          </AvatarFallback>
        </Avatar>
      )}
      {lookup.status === "new" && (
        <UserPlus className="size-3.5 shrink-0 text-muted-foreground" />
      )}
      <span className="truncate">
        {lookup.status === "known" && lookup.user?.full_name
          ? lookup.user.full_name
          : email}
      </span>
      {lookup.status === "new" && (
        <span className="shrink-0 text-muted-foreground">
          · will be invited
        </span>
      )}
      <button
        type="button"
        aria-label={`Remove ${email}`}
        disabled={disabled}
        onClick={onRemove}
        className="flex size-4 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-background hover:text-foreground"
      >
        <X className="size-3" />
      </button>
    </span>
  )
}

/**
 * A list of addresses built one chip at a time: type, then Enter or comma.
 * Keyboard first — Backspace on an empty field takes the previous chip back.
 */
export function EmailChipsInput({
  emails,
  onChange,
  lookups,
  disabled,
  placeholder = "colleague@company.com",
  "data-testid": testId,
}: EmailChipsInputProps) {
  const [draft, setDraft] = useState("")

  const commit = (raw: string) => {
    const candidates = splitCandidates(raw)
    if (candidates.length === 0) {
      setDraft("")
      return
    }
    const next = [...emails]
    for (const candidate of candidates) {
      const value = candidate.toLowerCase()
      if (!next.includes(value)) next.push(value)
    }
    onChange(next)
    setDraft("")
  }

  const remove = (email: string) => onChange(emails.filter((e) => e !== email))

  return (
    // A <label> rather than a <div>: clicking anywhere in the box lands on the
    // input by itself, with no click handler on a non-interactive element.
    <label className="flex min-h-9 w-full flex-wrap items-center gap-1.5 rounded-md border border-input bg-transparent px-2 py-1.5 text-sm shadow-xs transition-[color,box-shadow] focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50 dark:bg-input/30">
      {emails.map((email) => (
        <Chip
          key={email}
          email={email}
          lookup={lookups.get(email) ?? { status: "pending" }}
          disabled={disabled}
          onRemove={() => remove(email)}
        />
      ))}
      <input
        type="text"
        inputMode="email"
        autoComplete="off"
        // biome-ignore lint/a11y/noAutofocus: the dialog exists to type an address
        autoFocus
        aria-label="E-mail address"
        className="min-w-40 flex-1 bg-transparent outline-none placeholder:text-muted-foreground"
        placeholder={emails.length === 0 ? placeholder : ""}
        value={draft}
        disabled={disabled}
        data-testid={testId}
        onChange={(e) => {
          // A comma ends an address wherever it lands, including mid-paste.
          if (e.target.value.includes(",")) commit(e.target.value)
          else setDraft(e.target.value)
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === "," || e.key === "Tab") {
            if (draft.trim() === "") return
            e.preventDefault()
            commit(draft)
          } else if (e.key === "Backspace" && draft === "" && emails.length) {
            e.preventDefault()
            // Take the last chip back into the field so a typo can be fixed.
            const last = emails[emails.length - 1]
            onChange(emails.slice(0, -1))
            setDraft(last)
          }
        }}
        onPaste={(e) => {
          const text = e.clipboardData.getData("text")
          if (!/[,;\s]/.test(text)) return
          e.preventDefault()
          commit(`${draft}${text}`)
        }}
        onBlur={() => draft.trim() !== "" && commit(draft)}
      />
    </label>
  )
}
