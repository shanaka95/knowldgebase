import type { Editor, Range } from "@tiptap/core"
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  CheckSquare,
  Code2,
  Heading1,
  Heading2,
  Heading3,
  Image as ImageIcon,
  Info,
  List,
  ListOrdered,
  type LucideIcon,
  Minus,
  Pencil,
  Pilcrow,
  Quote,
  Table,
} from "lucide-react"

import { pickAndInsertImage, type UploadImageFn } from "../upload"

export interface SlashItem {
  title: string
  description: string
  icon: LucideIcon
  keywords: string[]
  group: "Basic" | "Advanced" | "Panels"
  run: (editor: Editor, range: Range) => void
}

export interface SlashContext {
  uploadImage?: UploadImageFn | null
}

export function buildSlashItems(ctx: SlashContext): SlashItem[] {
  return [
    {
      title: "Text",
      description: "Plain paragraph",
      icon: Pilcrow,
      keywords: ["paragraph", "p", "text"],
      group: "Basic",
      run: (editor, range) =>
        editor.chain().focus().deleteRange(range).setParagraph().run(),
    },
    {
      title: "Heading 1",
      description: "Large section heading",
      icon: Heading1,
      keywords: ["h1", "title", "heading"],
      group: "Basic",
      run: (editor, range) =>
        editor
          .chain()
          .focus()
          .deleteRange(range)
          .setHeading({ level: 1 })
          .run(),
    },
    {
      title: "Heading 2",
      description: "Medium section heading",
      icon: Heading2,
      keywords: ["h2", "subtitle", "heading"],
      group: "Basic",
      run: (editor, range) =>
        editor
          .chain()
          .focus()
          .deleteRange(range)
          .setHeading({ level: 2 })
          .run(),
    },
    {
      title: "Heading 3",
      description: "Small section heading",
      icon: Heading3,
      keywords: ["h3", "heading"],
      group: "Basic",
      run: (editor, range) =>
        editor
          .chain()
          .focus()
          .deleteRange(range)
          .setHeading({ level: 3 })
          .run(),
    },
    {
      title: "Bullet list",
      description: "Unordered list",
      icon: List,
      keywords: ["ul", "bullets", "list"],
      group: "Basic",
      run: (editor, range) =>
        editor.chain().focus().deleteRange(range).toggleBulletList().run(),
    },
    {
      title: "Numbered list",
      description: "Ordered list",
      icon: ListOrdered,
      keywords: ["ol", "numbers", "ordered"],
      group: "Basic",
      run: (editor, range) =>
        editor.chain().focus().deleteRange(range).toggleOrderedList().run(),
    },
    {
      title: "Task list",
      description: "Checklist with checkboxes",
      icon: CheckSquare,
      keywords: ["todo", "task", "checkbox", "checklist"],
      group: "Basic",
      run: (editor, range) =>
        editor.chain().focus().deleteRange(range).toggleTaskList().run(),
    },
    {
      title: "Quote",
      description: "Blockquote",
      icon: Quote,
      keywords: ["blockquote", "citation"],
      group: "Basic",
      run: (editor, range) =>
        editor.chain().focus().deleteRange(range).toggleBlockquote().run(),
    },
    {
      title: "Divider",
      description: "Horizontal rule",
      icon: Minus,
      keywords: ["hr", "rule", "separator", "line"],
      group: "Basic",
      run: (editor, range) =>
        editor.chain().focus().deleteRange(range).setHorizontalRule().run(),
    },
    {
      title: "Table",
      description: "3 × 3 table with a header row",
      icon: Table,
      keywords: ["grid", "rows", "columns"],
      group: "Advanced",
      run: (editor, range) =>
        editor
          .chain()
          .focus()
          .deleteRange(range)
          .insertTable({ rows: 3, cols: 3, withHeaderRow: true })
          .run(),
    },
    {
      title: "Code block",
      description: "Code with syntax highlighting",
      icon: Code2,
      keywords: ["code", "pre", "snippet"],
      group: "Advanced",
      run: (editor, range) =>
        editor.chain().focus().deleteRange(range).toggleCodeBlock().run(),
    },
    {
      title: "Image",
      description: "Upload an image",
      icon: ImageIcon,
      keywords: ["picture", "photo", "upload", "img"],
      group: "Advanced",
      run: (editor, range) => {
        editor.chain().focus().deleteRange(range).run()
        pickAndInsertImage(editor, ctx.uploadImage)
      },
    },
    {
      title: "Info panel",
      description: "Highlight useful information",
      icon: Info,
      keywords: ["panel", "callout", "info", "note"],
      group: "Panels",
      run: (editor, range) =>
        editor.chain().focus().deleteRange(range).setPanel("info").run(),
    },
    {
      title: "Note panel",
      description: "A side note",
      icon: Pencil,
      keywords: ["panel", "callout", "note"],
      group: "Panels",
      run: (editor, range) =>
        editor.chain().focus().deleteRange(range).setPanel("note").run(),
    },
    {
      title: "Success panel",
      description: "Confirm something worked",
      icon: CheckCircle2,
      keywords: ["panel", "callout", "success", "tip", "done"],
      group: "Panels",
      run: (editor, range) =>
        editor.chain().focus().deleteRange(range).setPanel("success").run(),
    },
    {
      title: "Warning panel",
      description: "Warn about a gotcha",
      icon: AlertTriangle,
      keywords: ["panel", "callout", "warning", "caution"],
      group: "Panels",
      run: (editor, range) =>
        editor.chain().focus().deleteRange(range).setPanel("warning").run(),
    },
    {
      title: "Error panel",
      description: "Call out a critical problem",
      icon: AlertOctagon,
      keywords: ["panel", "callout", "error", "danger"],
      group: "Panels",
      run: (editor, range) =>
        editor.chain().focus().deleteRange(range).setPanel("error").run(),
    },
  ]
}

export function filterSlashItems(
  items: SlashItem[],
  query: string,
): SlashItem[] {
  const q = query.trim().toLowerCase()
  if (!q) return items
  return items.filter(
    (item) =>
      item.title.toLowerCase().includes(q) ||
      item.keywords.some((k) => k.includes(q)),
  )
}
