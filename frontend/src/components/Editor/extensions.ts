import CodeBlockLowlight from "@tiptap/extension-code-block-lowlight"
import FileHandler from "@tiptap/extension-file-handler"
import Highlight from "@tiptap/extension-highlight"
import { TaskItem, TaskList } from "@tiptap/extension-list"
import Subscript from "@tiptap/extension-subscript"
import Superscript from "@tiptap/extension-superscript"
import { TableKit } from "@tiptap/extension-table"
import TextAlign from "@tiptap/extension-text-align"
import Typography from "@tiptap/extension-typography"
import { CharacterCount, Placeholder } from "@tiptap/extensions"
import type { Node as ProseMirrorNode } from "@tiptap/pm/model"
import StarterKit from "@tiptap/starter-kit"

import { lowlight } from "./lowlight"
import { AuthImage } from "./nodes/AuthImage"
import { Panel } from "./nodes/Panel"
import { SlashCommand } from "./slash/SlashCommand"
import { insertImageFromFile, type UploadImageFn } from "./upload"

export interface CreateExtensionsOptions {
  placeholder?: string
  /** Upload a dropped/pasted/picked image; null disables image insertion. */
  uploadImage?: UploadImageFn | null
  /** Fetch an attachment's bytes with credentials (for rendering stored images). */
  fetchAttachmentBlob?: ((attachmentId: string) => Promise<Blob>) | null
  /**
   * Which editor this is. "document" is the full set and the default, so a page
   * keeps exactly what it has today. A note is a card rather than a page:
   * tables, panels, alignment and sub/superscript are furniture it never uses
   * and a toolbar it has no room for on a phone.
   */
  variant?: "document" | "note"
  /**
   * Let a checkbox be ticked while the editor is read-only. That is what lets a
   * checklist be crossed off from its card in the list without opening it.
   * Returning true tells Tiptap the change was handled.
   */
  onTaskChecked?: (node: ProseMirrorNode, checked: boolean) => boolean
}

export function createExtensions({
  placeholder = "Type '/' for commands…",
  uploadImage = null,
  fetchAttachmentBlob = null,
  variant = "document",
  onTaskChecked,
}: CreateExtensionsOptions = {}) {
  const full = variant === "document"
  return [
    StarterKit.configure({
      heading: { levels: [1, 2, 3, 4] },
      codeBlock: false,
      link: {
        openOnClick: false,
        autolink: true,
        defaultProtocol: "https",
        HTMLAttributes: { rel: "noopener noreferrer", target: "_blank" },
      },
      dropcursor: { width: 2, class: "kb-dropcursor" },
    }),
    CodeBlockLowlight.configure({
      lowlight,
      defaultLanguage: "plaintext",
    }),
    ...(full
      ? [
          TableKit.configure({
            table: { resizable: false, HTMLAttributes: { class: "kb-table" } },
          }),
          TextAlign.configure({ types: ["heading", "paragraph"] }),
          Subscript,
          Superscript,
        ]
      : []),
    TaskList,
    TaskItem.configure({
      nested: true,
      ...(onTaskChecked ? { onReadOnlyChecked: onTaskChecked } : {}),
    }),
    Highlight,
    Typography,
    Placeholder.configure({
      placeholder: ({ node }) =>
        node.type.name === "heading" ? "Heading" : placeholder,
      includeChildren: false,
    }),
    CharacterCount,
    ...(full ? [Panel] : []),
    AuthImage.configure({ fetchAttachmentBlob }),
    SlashCommand.configure({ uploadImage }),
    FileHandler.configure({
      allowedMimeTypes: [
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/svg+xml",
      ],
      onDrop: (editor, files, pos) => {
        for (const file of files) {
          void insertImageFromFile(editor, file, uploadImage, pos)
        }
      },
      consumePasteEvent: true,
      onPaste: (editor, files, htmlContent) => {
        // let Tiptap handle rich HTML pastes that already contain <img>
        if (htmlContent && /<img/i.test(htmlContent)) return
        for (const file of files) {
          void insertImageFromFile(editor, file, uploadImage)
        }
      },
    }),
  ]
}
