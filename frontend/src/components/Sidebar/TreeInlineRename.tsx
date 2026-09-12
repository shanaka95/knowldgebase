import { useEffect, useRef, useState } from "react"

import { cn } from "@/lib/utils"

interface TreeInlineRenameProps {
  value: string
  onCommit: (value: string) => void
  onCancel: () => void
  className?: string
}

/** Swaps a tree label for an input; Enter/blur commits, Escape cancels. */
export function TreeInlineRename({
  value,
  onCommit,
  onCancel,
  className,
}: TreeInlineRenameProps) {
  const [draft, setDraft] = useState(value)
  const ref = useRef<HTMLInputElement>(null)
  const done = useRef(false)

  useEffect(() => {
    ref.current?.focus()
    ref.current?.select()
  }, [])

  const commit = () => {
    if (done.current) return
    done.current = true
    const next = draft.trim()
    if (!next || next === value) onCancel()
    else onCommit(next)
  }

  return (
    <input
      ref={ref}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault()
          commit()
        } else if (e.key === "Escape") {
          e.preventDefault()
          done.current = true
          onCancel()
        }
        e.stopPropagation()
      }}
      onClick={(e) => e.stopPropagation()}
      aria-label="Rename"
      data-testid="tree-rename-input"
      className={cn(
        "h-6 w-full min-w-0 rounded border border-primary bg-background px-1 text-sm outline-none ring-2 ring-primary/30",
        className,
      )}
    />
  )
}
