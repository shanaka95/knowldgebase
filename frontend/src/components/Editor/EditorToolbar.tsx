import type { Editor } from "@tiptap/core"
import { useEditorState } from "@tiptap/react"
import {
  Bold,
  CheckSquare,
  Code,
  Code2,
  Highlighter,
  Image as ImageIcon,
  Info,
  Italic,
  Link2,
  List,
  ListOrdered,
  Minus,
  Quote,
  Redo2,
  Strikethrough,
  Table,
  Underline,
  Undo2,
} from "lucide-react"

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { cn } from "@/lib/utils"
import { MenuButton, MenuDivider } from "./menus/MenuButton"
import { pickAndInsertImage, type UploadImageFn } from "./upload"

interface EditorToolbarProps {
  editor: Editor
  uploadImage?: UploadImageFn | null
  className?: string
  /** Extra controls rendered at the far right (e.g. save indicator). */
  trailing?: React.ReactNode
}

type BlockType =
  | "paragraph"
  | "heading1"
  | "heading2"
  | "heading3"
  | "heading4"
  | "codeBlock"

const BLOCK_LABELS: Record<BlockType, string> = {
  paragraph: "Text",
  heading1: "Heading 1",
  heading2: "Heading 2",
  heading3: "Heading 3",
  heading4: "Heading 4",
  codeBlock: "Code block",
}

export function EditorToolbar({
  editor,
  uploadImage,
  className,
  trailing,
}: EditorToolbarProps) {
  const s = useEditorState({
    editor,
    selector: ({ editor }) => {
      let block: BlockType = "paragraph"
      for (const level of [1, 2, 3, 4] as const) {
        if (editor.isActive("heading", { level })) block = `heading${level}`
      }
      if (editor.isActive("codeBlock")) block = "codeBlock"
      return {
        block,
        bold: editor.isActive("bold"),
        italic: editor.isActive("italic"),
        underline: editor.isActive("underline"),
        strike: editor.isActive("strike"),
        code: editor.isActive("code"),
        highlight: editor.isActive("highlight"),
        link: editor.isActive("link"),
        bulletList: editor.isActive("bulletList"),
        orderedList: editor.isActive("orderedList"),
        taskList: editor.isActive("taskList"),
        blockquote: editor.isActive("blockquote"),
        panel: editor.isActive("panel"),
        table: editor.isActive("table"),
        canUndo: editor.can().undo(),
        canRedo: editor.can().redo(),
        words:
          (
            editor.storage as { characterCount?: { words: () => number } }
          ).characterCount?.words() ?? 0,
      }
    },
  })

  const setBlock = (value: BlockType) => {
    const chain = editor.chain().focus()
    switch (value) {
      case "paragraph":
        chain.setParagraph().run()
        break
      case "codeBlock":
        chain.setCodeBlock().run()
        break
      default:
        chain
          .setHeading({ level: Number(value.slice(-1)) as 1 | 2 | 3 | 4 })
          .run()
    }
  }

  const setLink = () => {
    const previous = editor.getAttributes("link").href as string | undefined
    const url = window.prompt("Link URL", previous ?? "https://")
    if (url === null) return
    if (!url.trim()) {
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
    <div
      className={cn(
        "sticky top-14 z-10 -mx-4 flex items-center gap-1 overflow-x-auto border-b bg-background/95 px-4 py-1.5 backdrop-blur supports-[backdrop-filter]:bg-background/80 md:mx-0 md:rounded-lg md:border",
        className,
      )}
      role="toolbar"
      aria-label="Formatting"
      data-testid="editor-toolbar"
    >
      <MenuButton
        icon={Undo2}
        label="Undo"
        shortcut="⌘Z"
        disabled={!s.canUndo}
        onClick={() => editor.chain().focus().undo().run()}
      />
      <MenuButton
        icon={Redo2}
        label="Redo"
        shortcut="⌘⇧Z"
        disabled={!s.canRedo}
        onClick={() => editor.chain().focus().redo().run()}
      />
      <MenuDivider />
      <Select value={s.block} onValueChange={(v) => setBlock(v as BlockType)}>
        <SelectTrigger
          size="sm"
          className="h-8 w-32 shrink-0 text-xs"
          aria-label="Block type"
          onMouseDown={(e) => e.stopPropagation()}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.keys(BLOCK_LABELS) as BlockType[]).map((key) => (
            <SelectItem key={key} value={key} className="text-xs">
              {BLOCK_LABELS[key]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <MenuDivider />
      <MenuButton
        icon={Bold}
        label="Bold"
        shortcut="⌘B"
        active={s.bold}
        onClick={() => editor.chain().focus().toggleBold().run()}
      />
      <MenuButton
        icon={Italic}
        label="Italic"
        shortcut="⌘I"
        active={s.italic}
        onClick={() => editor.chain().focus().toggleItalic().run()}
      />
      <MenuButton
        icon={Underline}
        label="Underline"
        shortcut="⌘U"
        active={s.underline}
        onClick={() => editor.chain().focus().toggleUnderline().run()}
      />
      <MenuButton
        icon={Strikethrough}
        label="Strikethrough"
        active={s.strike}
        onClick={() => editor.chain().focus().toggleStrike().run()}
      />
      <MenuButton
        icon={Code}
        label="Inline code"
        shortcut="⌘E"
        active={s.code}
        onClick={() => editor.chain().focus().toggleCode().run()}
      />
      <MenuButton
        icon={Highlighter}
        label="Highlight"
        active={s.highlight}
        onClick={() => editor.chain().focus().toggleHighlight().run()}
      />
      <MenuButton icon={Link2} label="Link" active={s.link} onClick={setLink} />
      <MenuDivider />
      <MenuButton
        icon={List}
        label="Bullet list"
        active={s.bulletList}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
      />
      <MenuButton
        icon={ListOrdered}
        label="Numbered list"
        active={s.orderedList}
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
      />
      <MenuButton
        icon={CheckSquare}
        label="Task list"
        active={s.taskList}
        onClick={() => editor.chain().focus().toggleTaskList().run()}
      />
      <MenuButton
        icon={Quote}
        label="Quote"
        active={s.blockquote}
        onClick={() => editor.chain().focus().toggleBlockquote().run()}
      />
      <MenuDivider />
      <MenuButton
        icon={Table}
        label="Insert table"
        active={s.table}
        disabled={s.table}
        onClick={() =>
          editor
            .chain()
            .focus()
            .insertTable({ rows: 3, cols: 3, withHeaderRow: true })
            .run()
        }
      />
      <MenuButton
        icon={Code2}
        label="Code block"
        active={s.block === "codeBlock"}
        onClick={() => editor.chain().focus().toggleCodeBlock().run()}
      />
      <MenuButton
        icon={Info}
        label="Panel"
        shortcut="⌘⌥P"
        active={s.panel}
        onClick={() => editor.chain().focus().togglePanel("info").run()}
      />
      <MenuButton
        icon={ImageIcon}
        label="Image"
        disabled={!uploadImage}
        onClick={() => pickAndInsertImage(editor, uploadImage)}
      />
      <MenuButton
        icon={Minus}
        label="Divider"
        onClick={() => editor.chain().focus().setHorizontalRule().run()}
      />
      <span className="ml-auto flex shrink-0 items-center gap-3 pl-2 text-xs text-muted-foreground">
        <span className="hidden tabular-nums sm:inline">{s.words} words</span>
        {trailing}
      </span>
    </div>
  )
}

export default EditorToolbar
