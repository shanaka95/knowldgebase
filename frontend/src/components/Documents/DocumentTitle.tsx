import { useEffect, useRef } from "react"

import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

interface DocumentTitleProps {
  value: string
  editable: boolean
  onChange: (value: string) => void
  /** Called on Enter so the caller can focus the editor body. */
  onSubmit?: () => void
  className?: string
}

const TITLE_CLASS =
  "w-full bg-transparent text-3xl font-semibold leading-tight tracking-tight md:text-4xl"

export function DocumentTitle({
  value,
  editable,
  onChange,
  onSubmit,
  className,
}: DocumentTitleProps) {
  const ref = useRef<HTMLTextAreaElement>(null)

  // auto-grow
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = "0px"
    el.style.height = `${el.scrollHeight}px`
  }, [])

  if (!editable) {
    return (
      <h1
        className={cn(TITLE_CLASS, "break-words", className)}
        data-testid="document-title"
      >
        {value || "Untitled"}
      </h1>
    )
  }

  return (
    <Textarea
      ref={ref}
      value={value}
      rows={1}
      placeholder="Untitled"
      aria-label="Page title"
      data-testid="document-title-input"
      onChange={(e) => onChange(e.target.value.replace(/\n/g, ""))}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault()
          onSubmit?.()
        }
      }}
      className={cn(
        TITLE_CLASS,
        "min-h-0 resize-none overflow-hidden rounded-none border-0 px-0 py-0 shadow-none focus-visible:ring-0 placeholder:text-muted-foreground/50 md:text-4xl",
        className,
      )}
    />
  )
}

export default DocumentTitle
