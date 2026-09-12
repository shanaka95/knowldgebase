import type { Editor } from "@tiptap/core"
import { ListTree } from "lucide-react"
import { useEffect, useState } from "react"

import { cn } from "@/lib/utils"
import { deriveToc, scrollToHeading, type TocEntry } from "./toc"

interface TableOfContentsProps {
  editor: Editor | null
  className?: string
  minEntries?: number
}

export function useToc(editor: Editor | null): TocEntry[] {
  const [entries, setEntries] = useState<TocEntry[]>(() => deriveToc(editor))

  useEffect(() => {
    if (!editor) return
    let timer: ReturnType<typeof setTimeout> | null = null
    const update = () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => setEntries(deriveToc(editor)), 300)
    }
    setEntries(deriveToc(editor))
    editor.on("update", update)
    editor.on("create", update)
    return () => {
      editor.off("update", update)
      editor.off("create", update)
      if (timer) clearTimeout(timer)
    }
  }, [editor])

  return entries
}

export function TableOfContents({
  editor,
  className,
  minEntries = 2,
}: TableOfContentsProps) {
  const entries = useToc(editor)
  const [activeId, setActiveId] = useState<string | null>(null)

  useEffect(() => {
    if (!editor || entries.length === 0) return
    const headings = Array.from(
      editor.view.dom.querySelectorAll<HTMLElement>("h1, h2, h3, h4"),
    )
    if (headings.length === 0) return
    const observer = new IntersectionObserver(
      (observed) => {
        const visible = observed
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible.length > 0) {
          const idx = headings.indexOf(visible[0].target as HTMLElement)
          const entry = entries[idx]
          if (entry) setActiveId(entry.id)
        }
      },
      { rootMargin: "-80px 0px -70% 0px", threshold: [0, 1] },
    )
    for (const h of headings) observer.observe(h)
    return () => observer.disconnect()
  }, [editor, entries])

  if (!editor || entries.length < minEntries) return null

  const minLevel = Math.min(...entries.map((e) => e.level))

  return (
    <nav
      aria-label="Table of contents"
      className={cn("flex flex-col gap-2 text-sm", className)}
      data-testid="toc"
    >
      <div className="flex items-center gap-2 px-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <ListTree className="size-3.5" />
        On this page
      </div>
      <ul className="flex flex-col border-l">
        {entries.map((entry) => (
          <li key={entry.id}>
            <button
              type="button"
              onClick={() => scrollToHeading(editor, entry.pos)}
              className={cn(
                "-ml-px block w-full truncate border-l py-1 pr-2 text-left text-muted-foreground transition-colors hover:text-foreground",
                activeId === entry.id
                  ? "border-primary font-medium text-foreground"
                  : "border-transparent",
              )}
              style={{
                paddingLeft: `${0.75 + (entry.level - minLevel) * 0.75}rem`,
              }}
              title={entry.text}
            >
              {entry.text}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}

export default TableOfContents
