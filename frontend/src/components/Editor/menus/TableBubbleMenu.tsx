import type { Editor } from "@tiptap/core"
import { useEditorState } from "@tiptap/react"
import { BubbleMenu } from "@tiptap/react/menus"
import {
  ArrowDownToLine,
  ArrowLeftToLine,
  ArrowRightToLine,
  ArrowUpToLine,
  Columns3,
  Combine,
  Rows3,
  Split,
  Table2,
  TableProperties,
  Trash2,
} from "lucide-react"

import { MenuButton, MenuDivider, menuSurface } from "./MenuButton"

export function TableBubbleMenu({ editor }: { editor: Editor }) {
  const can = useEditorState({
    editor,
    selector: ({ editor }) => ({
      merge: editor.can().mergeCells(),
      split: editor.can().splitCell(),
    }),
  })

  return (
    <BubbleMenu
      editor={editor}
      pluginKey="tableBubbleMenu"
      updateDelay={100}
      options={{ placement: "top-start", offset: 8 }}
      shouldShow={({ editor }) => editor.isEditable && editor.isActive("table")}
      className={menuSurface}
    >
      <MenuButton
        icon={ArrowUpToLine}
        label="Add row above"
        onClick={() => editor.chain().focus().addRowBefore().run()}
      />
      <MenuButton
        icon={ArrowDownToLine}
        label="Add row below"
        onClick={() => editor.chain().focus().addRowAfter().run()}
      />
      <MenuButton
        icon={Rows3}
        label="Delete row"
        destructive
        onClick={() => editor.chain().focus().deleteRow().run()}
      />
      <MenuDivider />
      <MenuButton
        icon={ArrowLeftToLine}
        label="Add column left"
        onClick={() => editor.chain().focus().addColumnBefore().run()}
      />
      <MenuButton
        icon={ArrowRightToLine}
        label="Add column right"
        onClick={() => editor.chain().focus().addColumnAfter().run()}
      />
      <MenuButton
        icon={Columns3}
        label="Delete column"
        destructive
        onClick={() => editor.chain().focus().deleteColumn().run()}
      />
      <MenuDivider />
      <MenuButton
        icon={TableProperties}
        label="Toggle header row"
        onClick={() => editor.chain().focus().toggleHeaderRow().run()}
      />
      <MenuButton
        icon={Combine}
        label="Merge cells"
        disabled={!can.merge}
        onClick={() => editor.chain().focus().mergeCells().run()}
      />
      <MenuButton
        icon={Split}
        label="Split cell"
        disabled={!can.split}
        onClick={() => editor.chain().focus().splitCell().run()}
      />
      <MenuDivider />
      <MenuButton
        icon={Table2}
        label="Delete table"
        destructive
        onClick={() => editor.chain().focus().deleteTable().run()}
      />
      <span className="sr-only">
        <Trash2 />
      </span>
    </BubbleMenu>
  )
}
