import type { Editor as TiptapEditor } from "@tiptap/core"
import { EditorContent } from "@tiptap/react"

import { cn } from "@/lib/utils"
import { InlineBubbleMenu } from "./menus/InlineBubbleMenu"
import { LinkBubbleMenu } from "./menus/LinkBubbleMenu"
import { PanelBubbleMenu } from "./menus/PanelBubbleMenu"
import { TableBubbleMenu } from "./menus/TableBubbleMenu"

interface EditorProps {
  editor: TiptapEditor | null
  className?: string
  /** Render bubble menus (only meaningful while editable). */
  withMenus?: boolean
}

/**
 * Renders a Tiptap editor created with `useEditor(...)` (see `useDocumentEditor`).
 * View and edit modes share this component: toggle `editor.setEditable()`.
 */
export function Editor({ editor, className, withMenus = true }: EditorProps) {
  if (!editor) return null
  return (
    <div className={cn("kb-editor relative", className)} data-testid="editor">
      <EditorContent editor={editor} />
      {withMenus && (
        <>
          <InlineBubbleMenu editor={editor} />
          <LinkBubbleMenu editor={editor} />
          <TableBubbleMenu editor={editor} />
          <PanelBubbleMenu editor={editor} />
        </>
      )}
    </div>
  )
}

export default Editor
