import { type UseEditorOptions, useEditor } from "@tiptap/react"
import { useEffect } from "react"

import { type CreateExtensionsOptions, createExtensions } from "./extensions"

export interface UseDocumentEditorOptions extends CreateExtensionsOptions {
  content: string
  editable?: boolean
  onUpdate?: (html: string) => void
  autofocus?: UseEditorOptions["autofocus"]
}

/**
 * Creates the shared document editor. Content is only set on mount; callers
 * that need to replace it (e.g. after a conflict reload) call
 * `editor.commands.setContent(html, { emitUpdate: false })`.
 */
export function useDocumentEditor({
  content,
  editable = false,
  onUpdate,
  autofocus = false,
  ...extensionOptions
}: UseDocumentEditorOptions) {
  const editor = useEditor({
    extensions: createExtensions(extensionOptions),
    content,
    editable,
    autofocus,
    immediatelyRender: true,
    shouldRerenderOnTransaction: false,
    editorProps: {
      attributes: {
        class: "kb-prose focus:outline-none min-h-[50vh]",
        spellcheck: "true",
      },
    },
    onUpdate: ({ editor }) => {
      onUpdate?.(editor.getHTML())
    },
  })

  useEffect(() => {
    if (!editor) return
    if (editor.isEditable !== editable) {
      // `emitUpdate: false` — toggling view/edit is not a content change and
      // must not mark the document dirty / trigger an autosave.
      editor.setEditable(editable, false)
    }
  }, [editor, editable])

  return editor
}
