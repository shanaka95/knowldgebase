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
/** Is this extension loaded? A menu for one that is not would crash on its commands. */
function has(editor: TiptapEditor, name: string): boolean {
  return editor.extensionManager.extensions.some((ext) => ext.name === name)
}

export function Editor({ editor, className, withMenus = true }: EditorProps) {
  if (!editor) return null
  return (
    <div className={cn("kb-editor relative", className)} data-testid="editor">
      <EditorContent editor={editor} />
      {withMenus && (
        <>
          <InlineBubbleMenu editor={editor} />
          <LinkBubbleMenu editor={editor} />
          {/*
            Gated on the extension rather than rendered always. These menus call
            commands the extension registers - `mergeCells`, and the panel's own
            - and an editor built without it throws on the first render rather
            than quietly showing nothing. That is what a note does: it has no
            tables and no panels.
          */}
          {has(editor, "table") && <TableBubbleMenu editor={editor} />}
          {has(editor, "panel") && <PanelBubbleMenu editor={editor} />}
        </>
      )}
    </div>
  )
}

export default Editor
