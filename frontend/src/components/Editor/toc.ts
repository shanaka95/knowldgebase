import type { Editor } from "@tiptap/core"

export interface TocEntry {
  id: string
  level: number
  text: string
  pos: number
}

/** Derive a table of contents from the editor's heading nodes (no ids written to HTML). */
export function deriveToc(editor: Editor | null, maxLevel = 4): TocEntry[] {
  if (!editor) return []
  const entries: TocEntry[] = []
  editor.state.doc.descendants((node, pos) => {
    if (node.type.name === "heading" && node.attrs.level <= maxLevel) {
      const text = node.textContent.trim()
      if (text) {
        entries.push({
          id: `h-${pos}`,
          level: node.attrs.level as number,
          text,
          pos,
        })
      }
      return false
    }
    return true
  })
  return entries
}

export function scrollToHeading(editor: Editor, pos: number) {
  const dom = editor.view.nodeDOM(pos)
  if (dom instanceof HTMLElement) {
    dom.scrollIntoView({ block: "start", behavior: "smooth" })
  }
}
