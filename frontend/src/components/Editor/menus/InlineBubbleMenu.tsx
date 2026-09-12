import type { Editor } from "@tiptap/core"
import { isTextSelection } from "@tiptap/core"
import { useEditorState } from "@tiptap/react"
import { BubbleMenu } from "@tiptap/react/menus"
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Bold,
  Code,
  Highlighter,
  Italic,
  Link2,
  Strikethrough,
  Subscript,
  Superscript,
  Underline,
} from "lucide-react"

import { MenuButton, MenuDivider, menuSurface } from "./MenuButton"

export function InlineBubbleMenu({ editor }: { editor: Editor }) {
  const state = useEditorState({
    editor,
    selector: ({ editor }) => ({
      bold: editor.isActive("bold"),
      italic: editor.isActive("italic"),
      underline: editor.isActive("underline"),
      strike: editor.isActive("strike"),
      code: editor.isActive("code"),
      highlight: editor.isActive("highlight"),
      link: editor.isActive("link"),
      subscript: editor.isActive("subscript"),
      superscript: editor.isActive("superscript"),
      alignLeft: editor.isActive({ textAlign: "left" }),
      alignCenter: editor.isActive({ textAlign: "center" }),
      alignRight: editor.isActive({ textAlign: "right" }),
      editable: editor.isEditable,
    }),
  })

  const setLink = () => {
    const previous = editor.getAttributes("link").href as string | undefined
    const url = window.prompt("Link URL", previous ?? "https://")
    if (url === null) return
    if (url.trim() === "") {
      editor.chain().focus().extendMarkRange("link").unsetLink().run()
      return
    }
    editor
      .chain()
      .focus()
      .extendMarkRange("link")
      .setLink({ href: url.trim() })
      .run()
  }

  return (
    <BubbleMenu
      editor={editor}
      pluginKey="inlineBubbleMenu"
      options={{ placement: "top", offset: 8 }}
      shouldShow={({ editor, state, from, to }) => {
        if (!editor.isEditable) return false
        if (from === to) return false
        if (!isTextSelection(state.selection)) return false
        if (editor.isActive("codeBlock")) return false
        if (editor.isActive("image")) return false
        // table cell selections get their own menu
        if (state.selection.constructor.name === "CellSelection") return false
        return state.doc.textBetween(from, to).trim().length > 0
      }}
      className={menuSurface}
    >
      <MenuButton
        icon={Bold}
        label="Bold"
        shortcut="⌘B"
        active={state.bold}
        onClick={() => editor.chain().focus().toggleBold().run()}
      />
      <MenuButton
        icon={Italic}
        label="Italic"
        shortcut="⌘I"
        active={state.italic}
        onClick={() => editor.chain().focus().toggleItalic().run()}
      />
      <MenuButton
        icon={Underline}
        label="Underline"
        shortcut="⌘U"
        active={state.underline}
        onClick={() => editor.chain().focus().toggleUnderline().run()}
      />
      <MenuButton
        icon={Strikethrough}
        label="Strikethrough"
        shortcut="⌘⇧S"
        active={state.strike}
        onClick={() => editor.chain().focus().toggleStrike().run()}
      />
      <MenuButton
        icon={Code}
        label="Inline code"
        shortcut="⌘E"
        active={state.code}
        onClick={() => editor.chain().focus().toggleCode().run()}
      />
      <MenuButton
        icon={Highlighter}
        label="Highlight"
        shortcut="⌘⇧H"
        active={state.highlight}
        onClick={() => editor.chain().focus().toggleHighlight().run()}
      />
      <MenuDivider />
      <MenuButton
        icon={Link2}
        label="Link"
        shortcut="⌘K"
        active={state.link}
        onClick={setLink}
      />
      <MenuButton
        icon={Subscript}
        label="Subscript"
        active={state.subscript}
        onClick={() => editor.chain().focus().toggleSubscript().run()}
      />
      <MenuButton
        icon={Superscript}
        label="Superscript"
        active={state.superscript}
        onClick={() => editor.chain().focus().toggleSuperscript().run()}
      />
      <MenuDivider />
      <MenuButton
        icon={AlignLeft}
        label="Align left"
        active={state.alignLeft}
        onClick={() => editor.chain().focus().setTextAlign("left").run()}
      />
      <MenuButton
        icon={AlignCenter}
        label="Align center"
        active={state.alignCenter}
        onClick={() => editor.chain().focus().setTextAlign("center").run()}
      />
      <MenuButton
        icon={AlignRight}
        label="Align right"
        active={state.alignRight}
        onClick={() => editor.chain().focus().setTextAlign("right").run()}
      />
    </BubbleMenu>
  )
}
